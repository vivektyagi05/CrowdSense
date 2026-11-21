"""Smart stop search: normalise -> candidates -> ranking -> cluster grouping.

Ranking (highest first; every result carries ``match_type`` and ``score``):

    exact (1000) > alias (900) > prefix (800) > all_tokens (600..) > fuzzy (<=500) > partial_tokens (<=400)

Deviation from the Phase 4 spec's literal order (documented in ADR-07): a *fuzzy* match that accounts for every query token
ranks above *partial* matches, because a partial match silently ignores a word the passenger typed.

Tie-breakers: more routes served, then shorter normalised name, then stable stop_id.
Typo tolerance: bounded Levenshtein distance <= 2, only for query tokens of >= 5 characters.
All SQL is parameterised; the query text is never placed into SQL (it is matched in memory).
"""
from __future__ import annotations

import csv
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import BASE_DIR
from app.derived.names import normalise
from app.errors import AppError

log = logging.getLogger(__name__)
MIN_QUERY, MAX_QUERY, MAX_TOKENS = 2, 80, 8
FUZZY_MIN_TOKEN, FUZZY_MAX_EDITS = 5, 2
ALIAS_DIR = BASE_DIR / "data" / "aliases"
ALIAS_COLUMNS = ["alias", "stop_id_or_cluster_id", "source", "added_by", "added_on"]
BASE_SCORE = {"exact": 1000, "alias": 900, "prefix": 800, "all_tokens": 600, "fuzzy": 500, "partial_tokens": 400}
ROUTE_NAMES_IN_GROUP = 3


class AliasError(ValueError):
    """An alias file is invalid (unknown id, duplicate, missing column/provenance)."""


def load_aliases(directory: Path, stop_ids: set[str], cluster_ids: set[str]) -> dict[str, list[str]]:
    """Read ``*.csv`` alias files -> {normalised alias: [stop_id_or_cluster_id, ...]}.

    Every row needs a non-empty ``source`` and ``added_by`` (provenance), a referenced id that exists, and must not
    duplicate another (alias, target) pair. Raises :class:`AliasError` naming the file and line.
    """
    out: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as fh:
            lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
        reader = csv.DictReader(lines)
        if reader.fieldnames != ALIAS_COLUMNS:
            raise AliasError(f"{path.name}: header must be exactly {','.join(ALIAS_COLUMNS)}")
        for n, row in enumerate(reader, start=2):
            where = f"{path.name} line {n}"
            alias, target = normalise(row["alias"]), (row["stop_id_or_cluster_id"] or "").strip()
            if not alias:
                raise AliasError(f"{where}: empty alias")
            if not (row["source"] or "").strip() or not (row["added_by"] or "").strip() or not (row["added_on"] or "").strip():
                raise AliasError(f"{where}: source, added_by and added_on are required")
            if target not in stop_ids and target not in cluster_ids:
                raise AliasError(f"{where}: unknown stop_id/cluster_id {target!r}")
            if (alias, target) in seen:
                raise AliasError(f"{where}: duplicate alias {alias!r} -> {target!r}")
            seen.add((alias, target))
            out.setdefault(alias, []).append(target)
    return out


def bounded_levenshtein(a: str, b: str, limit: int) -> int:
    """Edit distance, or ``limit + 1`` as soon as it is certain to exceed ``limit``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        lo = min(cur[0], i)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            lo = min(lo, cur[j])
        if lo > limit:
            return limit + 1
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class Entry:
    stop_id: str
    name: str
    norm: str
    tokens: tuple[str, ...]
    routes: int
    cluster_id: str | None
    lat: float | None
    lon: float | None


class SearchIndex:
    def __init__(self, entries: list[Entry], clusters: dict[str, dict[str, Any]], aliases: dict[str, list[str]],
                 route_names: dict[str, list[str]]) -> None:
        self.entries = entries
        self.by_id = {e.stop_id: e for e in entries}
        self.clusters = clusters
        self.aliases = aliases
        self.route_names = route_names
        self.vocab = sorted({t for e in entries for t in e.tokens})
        self.vocab_by_len: dict[int, list[str]] = {}
        for t in self.vocab:
            self.vocab_by_len.setdefault(len(t), []).append(t)
        self._fuzzy_cache: dict[str, dict[str, int]] = {}      # token -> {vocab token: edits}; pure function of the vocabulary
        self.members: dict[str, list[Entry]] = {}
        for e in entries:
            if e.cluster_id:
                self.members.setdefault(e.cluster_id, []).append(e)

    # -- matching -------------------------------------------------------------------------------------------------
    def _fuzzy_map(self, qtokens: list[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for qt in qtokens:
            if len(qt) >= FUZZY_MIN_TOKEN and qt not in out:
                near = self._fuzzy_cache.get(qt)
                if near is None:
                    near = {}
                    for length in range(len(qt) - FUZZY_MAX_EDITS, len(qt) + FUZZY_MAX_EDITS + 1):   # only these lengths can be within 2 edits
                        for v in self.vocab_by_len.get(length, ()):
                            if v != qt:
                                d = bounded_levenshtein(qt, v, FUZZY_MAX_EDITS)
                                if d <= FUZZY_MAX_EDITS:
                                    near[v] = d
                    if len(self._fuzzy_cache) < 5000:                  # bounded: a hostile client cannot grow memory without limit
                        self._fuzzy_cache[qt] = near
                out[qt] = near
        return out

    def search(self, query: str, group_limit: int) -> list[dict[str, Any]]:
        qn = normalise(query)
        qtokens = qn.split(" ")[:MAX_TOKENS]
        fuzzy = self._fuzzy_map(qtokens)
        scored: dict[str, tuple[int, str]] = {}          # stop_id -> (score, match_type)

        def offer(stop_id: str, score: int, kind: str) -> None:
            if stop_id not in scored or score > scored[stop_id][0]:
                scored[stop_id] = (score, kind)

        for alias, targets in self.aliases.items():       # aliases: exact or prefix of the normalised alias
            if alias == qn or alias.startswith(qn):
                for t in targets:
                    for e in ([self.by_id[t]] if t in self.by_id else self.members.get(t, [])):
                        offer(e.stop_id, BASE_SCORE["alias"] - (0 if alias == qn else 20), "alias")

        for e in self.entries:
            if e.norm == qn:
                offer(e.stop_id, BASE_SCORE["exact"], "exact"); continue
            if e.norm.startswith(qn):
                offer(e.stop_id, BASE_SCORE["prefix"] - min(len(e.norm) - len(qn), 50), "prefix"); continue
            exact_tokens = prefix_tokens = fuzzy_tokens = edits = 0
            for qt in qtokens:
                best = None
                for nt in e.tokens:
                    if nt == qt:
                        best = (3, 0); break
                    if nt.startswith(qt) and len(qt) >= MIN_QUERY and (best is None or best[0] < 2):
                        best = (2, 0)
                    elif best is None and qt in fuzzy and nt in fuzzy[qt]:
                        best = (1, fuzzy[qt][nt])
                if best is None:
                    continue
                if best[0] == 3: exact_tokens += 1
                elif best[0] == 2: prefix_tokens += 1
                else: fuzzy_tokens += 1; edits += best[1]
            matched = exact_tokens + prefix_tokens + fuzzy_tokens
            if matched == len(qtokens):
                if fuzzy_tokens:
                    offer(e.stop_id, BASE_SCORE["fuzzy"] - 20 * edits - 5 * (len(e.tokens) - matched), "fuzzy")
                else:
                    offer(e.stop_id, BASE_SCORE["all_tokens"] + 10 * exact_tokens - 5 * (len(e.tokens) - matched), "all_tokens")
            elif matched >= 2 and matched * 2 >= len(qtokens):
                offer(e.stop_id, BASE_SCORE["partial_tokens"] * matched // len(qtokens) - 5 * (len(e.tokens) - matched), "partial_tokens")

        # rank stops, then group by cluster (stops with no cluster are their own group)
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1][0], -self.by_id[kv[0]].routes, len(self.by_id[kv[0]].norm), kv[0]))
        groups: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for stop_id, (score, kind) in ranked:
            e = self.by_id[stop_id]
            key = e.cluster_id or f"stop:{stop_id}"
            if key not in groups:
                c = self.clusters.get(e.cluster_id or "")
                groups[key] = {"cluster_id": e.cluster_id, "display_name": c["display_name"] if c else e.name,
                               "stop_count": c["stop_count"] if c else 1,
                               "centroid_lat": c["lat"] if c else e.lat, "centroid_lon": c["lon"] if c else e.lon,
                               "match_type": kind, "score": score, "members": []}
                order.append(key)
            groups[key]["members"].append({"stop_id": stop_id, "stop_name": e.name, "stop_lat": e.lat, "stop_lon": e.lon,
                                           "routes_count": e.routes, "route_names": self.route_names.get(stop_id, [])[:ROUTE_NAMES_IN_GROUP],
                                           "match_type": kind, "score": score})
        return [groups[k] for k in order[:group_limit]], len(order)   # type: ignore[return-value]


_CACHE: dict[tuple[str, int, int, str], SearchIndex] = {}
_LOCK = threading.Lock()


def _db_key(conn: sqlite3.Connection) -> tuple[str, int, int]:
    path = conn.execute("PRAGMA database_list").fetchone()[2] or ":memory:"
    try:
        st = Path(path).stat(); return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, 0, 0)


def _build_index(conn: sqlite3.Connection, alias_dir: Path) -> SearchIndex:
    has = lambda name: conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None
    cluster_of = dict(conn.execute("SELECT stop_id, cluster_id FROM cluster_members").fetchall()) if has("cluster_members") else {}
    clusters = {r[0]: {"display_name": r[1], "lat": r[2], "lon": r[3], "stop_count": r[4]}
                for r in conn.execute("SELECT cluster_id, display_name, centroid_lat, centroid_lon, stop_count FROM clusters")} if has("clusters") else {}
    if has("stop_routes"):
        rows = conn.execute("SELECT sr.stop_id, r.route_short_name, r.route_long_name, r.route_id, sr.call_count FROM stop_routes sr "
                            "JOIN routes r ON r.route_id = sr.route_id").fetchall()
    else:
        log.warning("derived data not built: computing route counts from stop_times (slow once); run python -m scripts.build_derived")
        rows = conn.execute("SELECT st.stop_id, r.route_short_name, r.route_long_name, r.route_id, COUNT(*) FROM stop_times st "
                            "JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id GROUP BY st.stop_id, r.route_id").fetchall()
    per: dict[str, list[tuple[int, str]]] = {}
    for sid, short, long_, rid, calls in rows:
        per.setdefault(sid, []).append((-calls, short or long_ or rid))
    route_names = {s: list(dict.fromkeys(n for _, n in sorted(v))) for s, v in per.items()}
    entries = []
    for r in conn.execute("SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops ORDER BY stop_id"):
        norm = normalise(r["stop_name"])
        entries.append(Entry(r["stop_id"], " ".join((r["stop_name"] or "").split()), norm, tuple(norm.split(" ")) if norm else (),
                             len(per.get(r["stop_id"], [])), cluster_of.get(r["stop_id"]), r["stop_lat"], r["stop_lon"]))
    entries = [e for e in entries if e.norm]
    try:
        aliases = load_aliases(alias_dir, {e.stop_id for e in entries}, set(clusters))
    except AliasError as exc:                      # a bad alias file must not take search down: log loudly, serve without aliases
        log.error("alias files rejected, serving WITHOUT aliases: %s", exc)
        aliases = {}
    return SearchIndex(entries, clusters, aliases, route_names)


def get_index(conn: sqlite3.Connection, alias_dir: Path | None = None) -> SearchIndex:
    alias_dir = alias_dir or ALIAS_DIR
    key = _db_key(conn) + (str(alias_dir),)
    idx = _CACHE.get(key)
    if idx is None:
        with _LOCK:
            idx = _CACHE.get(key)
            if idx is None:
                if len(_CACHE) > 4:
                    _CACHE.clear()
                idx = _CACHE[key] = _build_index(conn, alias_dir)
    return idx


def validate_query(raw: str) -> str:
    if len(raw) > MAX_QUERY:
        raise AppError(422, "validation_error", f"q must be at most {MAX_QUERY} characters.")
    qn = normalise(raw)
    if len(qn) < MIN_QUERY:
        raise AppError(422, "validation_error", "q must contain at least 2 letters or digits.")
    return qn


def _non_latin(text: str) -> bool:
    return any(ch.isalpha() and ord(ch) > 0x024F for ch in text)


def smart_search(conn: sqlite3.Connection, raw_q: str, limit: int) -> dict[str, Any]:
    validate_query(raw_q)
    groups, total_groups = get_index(conn).search(raw_q, limit)
    notice = None
    if not groups:
        notice = ("No stop matches. Stop names in the feed are in Latin script; text in other scripts is not transliterated "
                  "unless an alias exists." if _non_latin(raw_q) else "No stop matches this search.")
    items = [dict(m, cluster_id=g["cluster_id"]) for g in groups for m in g["members"]]
    return {"query": raw_q.strip(), "mode": "smart", "limit": limit, "total_groups": total_groups, "returned_groups": len(groups),
            "groups": groups, "items": items, "notice": notice}
