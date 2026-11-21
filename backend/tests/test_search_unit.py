"""Phase 4 / M6: ranking tiers, tie-breakers, alias loader, abuse protection (SYNTHETIC stops)."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.derived.build import build_derived
from app.gtfs.importer import import_gtfs
from app.main import create_app
from app.services import search_service as ss
from app.services.search_service import AliasError, bounded_levenshtein, load_aliases
from tests.gtfs_factory import build_zip

V = "/api/v1"
NAMES = {  # stop_id: name (spread over the NCR box so nothing clusters unless stated)
    "S01": "Park Gate", "S02": "Park Gate Road", "S03": "Main Park Gate", "S04": "Park Plaza Gate Two", "S05": "Park Market",
    "S06": "Central Market", "S07": "Centrel Market Annex", "S08": "Tie Stop", "S09": "Tie Stop", "S10": "Tie Stop Longer",
    "S11": "Old Fort", "S12": "Quick-Stop (North)", "S13": "Alias Target Name",
}


def _feed(extra_calls: dict[str, int] | None = None):
    stops = "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(f"{k},{v},{28.2 + i * 0.05:.5f},{77.0 + (i % 5) * 0.07:.5f}\n" for i, (k, v) in enumerate(NAMES.items()))
    times, trips = [], []
    # route counts: S08 served by 1 route, S09 by 3 routes (the tie-break must prefer S09)
    serve = {"S08": ["R1"], "S09": ["R1", "R2", "R3"], "S01": ["R1"]}
    n = 0
    for stop, routes in serve.items():
        for r in routes:
            n += 1; trips.append(f"{r},S1,T{n}\n"); times.append(f"T{n},08:00:00,08:00:00,{stop},1\n")
    for stop in NAMES:
        if stop not in serve:
            n += 1; trips.append(f"R1,S1,T{n}\n"); times.append(f"T{n},08:00:00,08:00:00,{stop},1\n")
    return {"stops.txt": stops, "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR1,1,One,3\nR2,2,Two,3\nR3,3,Three,3\n",
            "trips.txt": "route_id,service_id,trip_id\n" + "".join(trips),
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "".join(times),
            "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS1,1,1,1,1,1,1,1,20250101,20401231\n"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("srch")
    s = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(d / "s.sqlite3"), "GTFS_ZIP": str(d / "f.zip")})
    import_gtfs(build_zip(d / "f.zip", base=_feed()), s.database_path, promote_retries=0)
    build_derived(s.database_path)
    return TestClient(create_app(s), raise_server_exceptions=False), s, d


@pytest.fixture
def client(env, monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "ALIAS_DIR", tmp_path / "no-aliases")      # isolate from shipped alias files
    ss._CACHE.clear()
    return env[0]


def q(client, text, limit=20):
    r = client.get(f"{V}/stops", params={"q": text, "mode": "smart", "limit": limit})
    assert r.status_code == 200, r.text
    return r.json()


def test_ranking_tiers_in_documented_order(client):
    j = q(client, "park gate")
    got = [(i["stop_id"], i["match_type"]) for i in j["items"]]
    assert got[0] == ("S01", "exact")                                  # exact
    assert got[1] == ("S02", "prefix")                                 # prefix
    assert {s for s, t in got if t == "all_tokens"} == {"S03", "S04"}  # all tokens, any position/order
    assert [t for _, t in got] == sorted([t for _, t in got], key=["exact", "alias", "prefix", "all_tokens", "fuzzy", "partial_tokens"].index)
    assert "S05" not in {s for s, _ in got}                            # 1 matched token of 2 is not enough for a partial match


def test_partial_tokens_need_two_matches_covering_at_least_half(client):
    j = q(client, "park gate plaza")
    types = {i["stop_id"]: i["match_type"] for i in j["items"]}
    assert types["S04"] == "all_tokens"                                 # Park Plaza Gate Two: all three tokens
    assert types["S01"] == "partial_tokens" and types["S02"] == "partial_tokens"   # 2 of 3 tokens
    assert "S05" not in types                                           # only 'park' matches: 1 of 3
    order = [i["stop_id"] for i in j["items"]]
    assert order.index("S04") < order.index("S01")                     # all_tokens above partial


def test_fuzzy_ranks_above_partial_and_below_all_tokens(client):
    j = q(client, "central market")
    types = {i["stop_id"]: i["match_type"] for i in j["items"]}
    assert types["S06"] == "exact" and types["S07"] == "fuzzy"       # 'Centrel' is 1 edit from 'central' (>= 5 chars)
    scores = {i["stop_id"]: i["score"] for i in j["items"]}
    assert scores["S06"] > scores["S07"]


def test_typo_needs_five_characters(client):
    assert not any(i["stop_id"] == "S01" for i in q(client, "prak gate")["items"] if i["match_type"] == "fuzzy")   # 'prak' is 4 chars: no fuzzy
    assert any(i["stop_id"] == "S11" for i in q(client, "old frot")["items"]) is False                              # 'frot' 4 chars
    assert any(i["stop_id"] == "S11" for i in q(client, "fortt")["items"])                                          # 5 chars, 1 edit


def test_tie_breakers_routes_then_shorter_name_then_stable_id(client):
    items = q(client, "tie stop")["items"]
    assert [i["stop_id"] for i in items[:2]] == ["S09", "S08"]         # same score: more routes (3 vs 1) first
    assert items[2]["stop_id"] == "S10"                                 # prefix of a longer name ranks below the two exact matches
    j = q(client, "park gate road")
    assert j["items"][0]["stop_id"] == "S02"


def test_punctuation_case_and_spacing_are_normalised(client):
    for text in ("QUICK STOP NORTH", "quick-stop (north)", "  quick   stop   north ", "Quick.Stop,North"):
        assert q(client, text)["items"][0]["stop_id"] == "S12", text


def test_no_cluster_means_group_per_stop_and_notice_on_empty(client):
    j = q(client, "park gate")
    assert all(g["stop_count"] >= 1 for g in j["groups"]) and j["notice"] is None
    assert q(client, "nothing matches this")["notice"] == "No stop matches this search."


# --- abuse protection -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("params", [{"q": "a", "mode": "smart"}, {"q": "!!", "mode": "smart"}, {"q": "x" * 81, "mode": "smart"},
                                    {"mode": "smart"}, {"q": "park", "mode": "smart", "limit": 51}, {"q": "park", "mode": "smart", "limit": 0},
                                    {"q": "park", "mode": "smart", "offset": 5}, {"q": "park", "mode": "smart", "bbox": "1,1,2,2"},
                                    {"q": "park", "mode": "bogus"}])
def test_invalid_requests_are_422_not_500(client, params):
    r = client.get(f"{V}/stops", params=params)
    assert r.status_code == 422, (params, r.status_code)


@pytest.mark.parametrize("text", ["'; DROP TABLE stops; --", "park' OR '1'='1", "%_%", "\\", "\x00park", "park\n\r\t", "😀😀", "ＰＡＲＫ", "a" * 80,
                                  "park " * 15, "कश्मीरी", "$(rm -rf /)", "<script>alert(1)</script>"])
def test_hostile_input_never_errors_and_never_touches_data(client, env, text):
    r = client.get(f"{V}/stops", params={"q": text, "mode": "smart"})
    assert r.status_code in (200, 422), (text, r.status_code)
    c = sqlite3.connect(env[1].database_path)
    assert c.execute("select count(*) from stops").fetchone()[0] == len(NAMES)
    c.close()


def test_fullwidth_input_is_normalised(client):
    assert q(client, "ＰＡＲＫ ＧＡＴＥ")["items"][0]["stop_id"] == "S01"


def test_substring_mode_is_untouched(client):
    j = client.get(f"{V}/stops", params={"q": "park"}).json()
    assert "groups" not in j and j["total"] >= 4 and set(j) >= {"items", "total", "limit", "offset"}


# --- bounded edit distance ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("a,b,limit,want", [("kitten", "sitting", 3, 3), ("kitten", "sitting", 2, 3), ("abc", "abc", 2, 0), ("abc", "abd", 2, 1),
                                            ("rithala", "rihala", 2, 1), ("aaaaaaaa", "b", 2, 3), ("", "ab", 2, 2), ("kashmere", "kashmiri", 2, 2)])
def test_bounded_levenshtein(a, b, limit, want):
    assert bounded_levenshtein(a, b, limit) == want      # returns limit+1 once it is certain the distance exceeds the limit


# --- alias loader -------------------------------------------------------------------------------------------------------
HEADER = "alias,stop_id_or_cluster_id,source,added_by,added_on\n"
IDS, CLS = {"S01", "S02"}, {"c_abc"}


def write(tmp_path, body, name="a.csv"):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_loader_accepts_valid_rows_comments_and_cluster_targets(tmp_path):
    d = write(tmp_path, "# comment\n" + HEADER + "Old Name,S01,GTFS stops.txt line 5,reviewer-1,2026-11-01\n\nNew-Name!,c_abc,agency notice 12,reviewer-2,2026-11-02\n")
    assert load_aliases(d, IDS, CLS) == {"old name": ["S01"], "new name": ["c_abc"]}


@pytest.mark.parametrize("body,msg", [
    ("alias,target\nx,S01\n", "header must be exactly"),
    (HEADER + "x,NOPE,src,me,2026-01-01\n", "unknown stop_id/cluster_id"),
    (HEADER + "x,S01,src,me,2026-01-01\nX,S01,src,me,2026-01-01\n", "duplicate alias"),
    (HEADER + "x,S01,,me,2026-01-01\n", "source, added_by and added_on are required"),
    (HEADER + "x,S01,src,,2026-01-01\n", "source, added_by and added_on are required"),
    (HEADER + "x,S01,src,me,\n", "source, added_by and added_on are required"),
    (HEADER + "  !!  ,S01,src,me,2026-01-01\n", "empty alias"),
])
def test_loader_rejects_bad_files(tmp_path, body, msg):
    with pytest.raises(AliasError, match=msg):
        load_aliases(write(tmp_path, body), IDS, CLS)


def test_loader_missing_directory_is_empty(tmp_path):
    assert load_aliases(tmp_path / "nope", IDS, CLS) == {}


def test_shipped_alias_files_are_valid_against_the_real_ids():
    """Whatever is committed under data/aliases must load against the real database, when it is present."""
    from app.config import BASE_DIR
    db = BASE_DIR / "data" / "crowdsense.sqlite3"
    if not db.exists():
        pytest.skip("real database not imported")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    stops = {r[0] for r in c.execute("select stop_id from stops")}
    clusters = {r[0] for r in c.execute("select cluster_id from clusters")} if c.execute("select 1 from sqlite_master where name='clusters'").fetchone() else set()
    c.close()
    load_aliases(ss.ALIAS_DIR, stops, clusters)


def test_alias_drives_search_with_its_own_match_type(env, monkeypatch, tmp_path):
    d = write(tmp_path, HEADER + "Alias Phrase,S13,test fixture,tester,2026-11-14\n")
    monkeypatch.setattr(ss, "ALIAS_DIR", d); ss._CACHE.clear()
    j = q(env[0], "alias phrase")
    assert j["items"][0]["stop_id"] == "S13" and j["items"][0]["match_type"] == "alias"
    assert q(env[0], "alias ph")["items"][0]["match_type"] == "alias"      # alias prefix works too, scored lower
    ss._CACHE.clear()


def test_invalid_alias_file_degrades_to_no_aliases_instead_of_500(env, monkeypatch, tmp_path, caplog):
    d = write(tmp_path, HEADER + "Alias Phrase,NOPE,test,tester,2026-11-14\n")
    monkeypatch.setattr(ss, "ALIAS_DIR", d); ss._CACHE.clear()
    j = q(env[0], "alias phrase")
    assert j["items"] == [] and "alias files rejected" in caplog.text
    ss._CACHE.clear()
