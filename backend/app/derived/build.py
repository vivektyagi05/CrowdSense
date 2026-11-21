"""Idempotent, deterministic build of every derived table from the imported GTFS.

Rebuilds (in ONE transaction, so readers never see a half-built state):
  stop_routes      (stop_id, route_id, call_count)        which routes serve a stop, with scheduled call counts
  stops_rtree      R-tree virtual table over stop points   (or stops_grid when the R-tree module is unavailable)
  clusters / cluster_members                               place clusters (same normalised name + complete linkage)
  derived_meta     (key, value)                            method, parameters, content hash, build timestamp

Same input => same ``content_hash`` (timestamps are metadata and excluded from the hash).
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.derived.names import normalise
from app.geo.planar import haversine_m

DERIVED_VERSION = 1
CLUSTER_THRESHOLD_M = 150.0         # ADR-05: chosen from the M1 histograms
GRID_CELL_DEG = 0.005               # ~555 m
DERIVED_TABLES = ("stop_routes", "clusters", "cluster_members", "stops_grid", "stops_rtree", "derived_meta")


def _drop_all(conn: sqlite3.Connection) -> None:
    for t in ("stops_rtree",):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    for t in ("stop_routes", "clusters", "cluster_members", "stops_grid", "derived_meta"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")


def rtree_available(conn: sqlite3.Connection) -> bool:
    return any("ENABLE_RTREE" in r[0] for r in conn.execute("PRAGMA compile_options"))


def cluster_stops(stops: list[tuple[str, float, float]], threshold_m: float) -> list[list[str]]:
    """Complete-linkage agglomerative clustering of the stops that share one normalised name.

    Merge the two clusters with the smallest *maximum* pairwise distance while that maximum is <= threshold.
    Ties are broken by the sorted member ids, so the result does not depend on input order.
    """
    clusters: list[list[tuple[str, float, float]]] = [[s] for s in sorted(stops)]
    while len(clusters) > 1:
        best: tuple[float, tuple[str, ...], tuple[str, ...], int, int] | None = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = max(haversine_m(a[1], a[2], b[1], b[2]) for a in clusters[i] for b in clusters[j])
                if d <= threshold_m:
                    key = (round(d, 6), tuple(sorted(x[0] for x in clusters[i])), tuple(sorted(x[0] for x in clusters[j])), i, j)
                    if best is None or key < best:
                        best = key
        if best is None:
            break
        i, j = best[3], best[4]
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]
    return [sorted(m[0] for m in c) for c in clusters]


def cluster_id_for(member_ids: list[str]) -> str:
    return "c_" + hashlib.sha1("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()[:12]


def _display_name(raw_names: list[str]) -> str:
    """Most frequent raw spelling; ties -> the one that sorts first. Deterministic."""
    counts: dict[str, int] = defaultdict(int)
    for n in raw_names:
        counts[" ".join(n.split())] += 1          # collapse whitespace so '  ' variants vote together
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _canonical_hash(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for sql in ("SELECT stop_id, route_id, call_count FROM stop_routes ORDER BY stop_id, route_id",
                "SELECT cluster_id, display_name, round(centroid_lat, 7), round(centroid_lon, 7), stop_count FROM clusters ORDER BY cluster_id",
                "SELECT cluster_id, stop_id FROM cluster_members ORDER BY cluster_id, stop_id"):
        for row in conn.execute(sql):
            h.update(repr(tuple(row)).encode("utf-8")); h.update(b"\n")
        h.update(b"--\n")
    spatial = "stops_rtree" if conn.execute("SELECT 1 FROM sqlite_master WHERE name='stops_rtree'").fetchone() else "stops_grid"
    h.update(spatial.encode())
    if spatial == "stops_rtree":
        rows = conn.execute("SELECT s.stop_id FROM stops_rtree r JOIN stops s ON s.rowid = r.id ORDER BY s.stop_id").fetchall()
    else:
        rows = conn.execute("SELECT stop_id, cell_lat, cell_lon FROM stops_grid ORDER BY stop_id").fetchall()
    for row in rows:
        h.update(repr(tuple(row)).encode("utf-8"))
    return h.hexdigest()


def _source_fingerprint(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for row in conn.execute("SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops ORDER BY stop_id"):
        h.update(repr(tuple(row)).encode("utf-8"))
    for t in ("trips", "stop_times", "routes"):
        h.update(f"{t}={conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}".encode())
    return h.hexdigest()


def build_derived(db_path: Path | str, *, force_grid: bool = False, cluster_threshold_m: float = CLUSTER_THRESHOLD_M,
                  now: datetime | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        _drop_all(conn)
        conn.execute("CREATE TABLE stop_routes(stop_id TEXT NOT NULL, route_id TEXT NOT NULL, call_count INTEGER NOT NULL, "
                     "PRIMARY KEY(stop_id, route_id)) WITHOUT ROWID")
        conn.execute("INSERT INTO stop_routes SELECT st.stop_id, t.route_id, COUNT(*) FROM stop_times st "
                     "JOIN trips t ON t.trip_id = st.trip_id GROUP BY st.stop_id, t.route_id ORDER BY st.stop_id, t.route_id")
        conn.execute("CREATE INDEX idx_stop_routes_route ON stop_routes(route_id)")

        points = conn.execute("SELECT rowid AS rid, stop_id, stop_name, stop_lat, stop_lon FROM stops "
                              "WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL ORDER BY stop_id").fetchall()
        use_rtree = rtree_available(conn) and not force_grid
        if use_rtree:
            conn.execute("CREATE VIRTUAL TABLE stops_rtree USING rtree(id, min_lat, max_lat, min_lon, max_lon)")
            conn.executemany("INSERT INTO stops_rtree VALUES (?,?,?,?,?)",
                             [(p["rid"], p["stop_lat"], p["stop_lat"], p["stop_lon"], p["stop_lon"]) for p in points])
            method = "rtree"
        else:
            conn.execute("CREATE TABLE stops_grid(cell_lat INTEGER NOT NULL, cell_lon INTEGER NOT NULL, stop_id TEXT NOT NULL, "
                         "PRIMARY KEY(cell_lat, cell_lon, stop_id)) WITHOUT ROWID")
            conn.executemany("INSERT INTO stops_grid VALUES (?,?,?)",
                             [(math.floor(p["stop_lat"] / GRID_CELL_DEG), math.floor(p["stop_lon"] / GRID_CELL_DEG), p["stop_id"]) for p in points])
            method = "grid"

        conn.execute("CREATE TABLE clusters(cluster_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, centroid_lat REAL NOT NULL, "
                     "centroid_lon REAL NOT NULL, stop_count INTEGER NOT NULL) WITHOUT ROWID")
        conn.execute("CREATE TABLE cluster_members(cluster_id TEXT NOT NULL REFERENCES clusters(cluster_id), "
                     "stop_id TEXT NOT NULL UNIQUE, PRIMARY KEY(cluster_id, stop_id)) WITHOUT ROWID")
        groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for p in points:
            groups[normalise(p["stop_name"]) or f"\x00{p['stop_id']}"].append(p)     # nameless stops never merge
        by_id = {p["stop_id"]: p for p in points}
        n_clusters = 0
        for key in sorted(groups):
            members = groups[key]
            for ids in cluster_stops([(m["stop_id"], m["stop_lat"], m["stop_lon"]) for m in members], cluster_threshold_m):
                ps = [by_id[i] for i in ids]
                cid = cluster_id_for(ids)
                conn.execute("INSERT INTO clusters VALUES (?,?,?,?,?)",
                             (cid, _display_name([p["stop_name"] or "" for p in ps]),
                              sum(p["stop_lat"] for p in ps) / len(ps), sum(p["stop_lon"] for p in ps) / len(ps), len(ps)))
                conn.executemany("INSERT INTO cluster_members VALUES (?,?)", [(cid, i) for i in ids])
                n_clusters += 1

        headsigns = bool(conn.execute("SELECT EXISTS(SELECT 1 FROM trips WHERE trip_headsign IS NOT NULL AND trim(trip_headsign) <> '')").fetchone()[0]
                         or conn.execute("SELECT EXISTS(SELECT 1 FROM stop_times WHERE stop_headsign IS NOT NULL AND trim(stop_headsign) <> '')").fetchone()[0])
        content_hash = _canonical_hash(conn)
        meta = {"derived_version": str(DERIVED_VERSION), "spatial_method": method, "cluster_threshold_m": str(cluster_threshold_m),
                "cluster_rule": "same normalised name + complete linkage", "content_hash": content_hash,
                "source_fingerprint": _source_fingerprint(conn), "headsigns_available": "true" if headsigns else "false", "stop_count": str(len(points)), "cluster_count": str(n_clusters),
                "built_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
        conn.execute("CREATE TABLE derived_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
        conn.executemany("INSERT INTO derived_meta VALUES (?,?)", sorted(meta.items()))
        conn.commit()
        return meta
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
