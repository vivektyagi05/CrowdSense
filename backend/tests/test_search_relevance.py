"""Phase 4 / M6: relevance suite on the REAL Delhi database. Expected results come from independent SQL over the real
stop names (never from the engine's own output). Skipped unless the DB exists AND ``scripts.build_derived`` has been run."""
from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.derived.names import normalise
from app.main import create_app

REAL_DB = BASE_DIR / "data" / "crowdsense.sqlite3"


def _ready() -> bool:
    if not REAL_DB.exists():
        return False
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        return c.execute("select 1 from sqlite_master where name='derived_meta'").fetchone() is not None
    finally:
        c.close()


pytestmark = pytest.mark.skipif(not _ready(), reason="real DB not imported/derived (python -m scripts.import_gtfs && python -m scripts.build_derived)")
V = "/api/v1"
# Real stop names (all verified present in the Delhi feed); n = number of stops sharing that normalised name
NAMES = ["AIIMS", "Hamidpur Village", "Dhaka Village", "Rithala Metro Station", "Rajiv Chowk Metro Station", "Hindon Regulator(BRD)",
         "Anand Vihar ISBT", "Hari Nagar Depot", "Dwarka International School", "Delhi University / North Campus",
         "Punjabi Bagh Market / West Punjabi Bagh", "Saket A block(Malviya Nagar Metro Station)", "Kailash Colony Metro Station",
         "Nangloi Depot / Jwala Puri", "Lajpat Nagar", "Nehru Place"]


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Settings.from_env({"APP_ENV": "test"})), raise_server_exceptions=False)


@pytest.fixture(scope="module")
def truth():
    """normalised name -> stop ids, straight from SQL on the real data."""
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    out: dict[str, set[str]] = {}
    for sid, name in c.execute("select stop_id, stop_name from stops"):
        out.setdefault(normalise(name), set()).add(sid)
    c.close()
    return out


def search(client, q, limit=10):
    r = client.get(f"{V}/stops", params={"q": q, "mode": "smart", "limit": limit})
    assert r.status_code == 200, (q, r.status_code, r.text[:200])
    return r.json()


def ids_in_top(j, k):
    return {m["stop_id"] for g in j["groups"][:k] for m in g["members"]}


def typo(name):
    toks = name.split()
    i = max(range(len(toks)), key=lambda x: len(toks[x]))
    t = toks[i]
    if len(normalise(t)) < 6:
        return None
    toks[i] = t[:2] + t[3:]            # drop the third letter
    return " ".join(toks)


def swap(name):
    toks = name.split()
    i = max(range(len(toks)), key=lambda x: len(toks[x]))
    t = toks[i]
    if len(normalise(t)) < 6:
        return None
    toks[i] = t[:1] + t[2] + t[1] + t[3:]   # transpose letters 2 and 3
    return " ".join(toks)


def build_cases():
    cases = []
    for n in NAMES:
        cases.append(("exact", n, n))
        cases.append(("upper", n.upper(), n))
        cases.append(("spacing", "  " + "   ".join(n.split()) + " ", n))
        cases.append(("punct", n.replace("/", " - ").replace("(", " [").replace(")", "] ,"), n))
        for kind, f in (("typo", typo), ("transposition", swap)):
            if f(n):
                cases.append((kind, f(n), n))
        toks = normalise(n).split()
        if len(toks) >= 2:
            cases.append(("reordered", " ".join(reversed(toks)), n))
            cases.append(("prefix", toks[0] + " " + toks[1][:3], n))
    return cases


CASES = build_cases()


def test_suite_has_at_least_40_real_cases():
    assert len(CASES) >= 40, len(CASES)


@pytest.mark.parametrize("kind,query,name", CASES, ids=[f"{k}:{q[:40]}" for k, q, _ in CASES])
def test_relevance(client, truth, kind, query, name):
    want = truth[normalise(name)]
    j = search(client, query, limit=10)
    if kind in ("exact", "upper", "spacing", "punct"):
        # every stop with this exact normalised name must come first, as 'exact' matches, before anything else
        exact_groups = [g for g in j["groups"] if g["match_type"] == "exact"]
        assert exact_groups and j["groups"][0]["match_type"] == "exact", (query, [g["match_type"] for g in j["groups"][:3]])
        got = {m["stop_id"] for g in exact_groups for m in g["members"]}
        assert got == want
        first_non_exact = next((i for i, g in enumerate(j["groups"]) if g["match_type"] != "exact"), len(j["groups"]))
        assert len(exact_groups) == first_non_exact          # exact groups are contiguous at the top
    elif kind in ("typo", "transposition"):
        assert want <= ids_in_top(j, 5), (query, j["groups"][0]["display_name"])
    elif kind == "reordered":
        assert want <= ids_in_top(j, 5), (query, [g["display_name"] for g in j["groups"][:5]])
    else:  # prefix: correctness and COMPLETENESS of the prefix set (a 3-letter fragment can have dozens of valid matches)
        j = search(client, query, limit=50)
        prefix_groups = [g for g in j["groups"] if g["match_type"] == "prefix"]
        assert want <= {m["stop_id"] for g in prefix_groups for m in g["members"]}, query
        assert all(normalise(g["display_name"]).startswith(normalise(query)) or any(normalise(m["stop_name"]).startswith(normalise(query)) for m in g["members"]) for g in prefix_groups)
        first_non_prefix = next((i for i, g in enumerate(j["groups"]) if g["match_type"] not in ("exact", "alias", "prefix")), len(j["groups"]))
        assert len(prefix_groups) <= first_non_prefix                      # prefix matches are ranked above every weaker kind


def test_duplicate_names_are_grouped_into_place_clusters_with_every_member(client, truth):
    j = search(client, "Rithala Metro Station")
    g = j["groups"][0]
    assert g["stop_count"] == 4 and {m["stop_id"] for m in g["members"]} == truth["rithala metro station"] and g["cluster_id"].startswith("c_")
    j = search(client, "Hari Nagar Depot")      # 6 stops, split into two clusters by the 150 m rule
    assert {m["stop_id"] for gr in j["groups"] if gr["match_type"] == "exact" for m in gr["members"]} == truth["hari nagar depot"]
    assert len([gr for gr in j["groups"] if gr["match_type"] == "exact"]) == 2


def test_items_flatten_groups_in_ranked_order(client):
    j = search(client, "anand vihar")
    assert [i["stop_id"] for i in j["items"]] == [m["stop_id"] for g in j["groups"] for m in g["members"]]
    assert all("cluster_id" in i for i in j["items"])


def test_real_world_typo_variants_of_one_place(client):
    """Kashmere / Kashmiri / Kashmire all occur or are within 2 edits: a passenger typing any spelling finds the ISBT."""
    for q in ("kashmere gate", "kashmiri gate", "kashmire gate"):
        names = [g["display_name"] for g in search(client, q, limit=15)["groups"]]
        assert "ISBT Kashmere Gate" in names, (q, names)


def test_devanagari_does_not_crash_and_is_honestly_empty(client):
    j = search(client, "कश्मीरी गेट")
    assert j["groups"] == [] and j["items"] == [] and "not transliterated" in j["notice"]


def test_no_match_is_empty_with_notice(client):
    j = search(client, "zzzzqqqq xxxxwwww")
    assert j["groups"] == [] and j["notice"]


def test_p95_latency_under_150ms_over_200_queries(client, truth):
    import random
    rnd = random.Random(3)
    names = sorted(truth)
    qs = []
    for _ in range(200):
        n = rnd.choice(names)
        kind = rnd.choice(["exact", "prefix", "typo", "reorder", "partial"])
        toks = n.split()
        if kind == "exact": q = n
        elif kind == "prefix": q = n[: max(3, len(n) // 2)]
        elif kind == "typo": q = n[:3] + n[4:] if len(n) > 6 else n
        elif kind == "reorder": q = " ".join(reversed(toks))
        else: q = toks[0] if len(toks[0]) >= 2 else n
        qs.append(q if len(q.strip()) >= 2 else "ka")
    search(client, "warm up")
    ts = []
    for q in qs:
        t = time.perf_counter(); r = client.get(f"{V}/stops", params={"q": q, "mode": "smart", "limit": 20}); ts.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    ts.sort()
    assert ts[int(0.95 * len(ts)) - 1] < 150, f"p95={ts[int(0.95 * len(ts)) - 1]:.1f} ms"
