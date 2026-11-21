"""Phase 4 / M5: normalisation, cluster rules (merge / no-merge edges), determinism, /clusters API (SYNTHETIC stops)."""
from __future__ import annotations

import random
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.derived.build import build_derived, cluster_id_for, cluster_stops
from app.derived.names import normalise
from app.geo.planar import haversine_m
from app.gtfs.importer import import_gtfs
from app.main import create_app
from tests.gtfs_factory import build_zip

V = "/api/v1"
DLAT_M = 1 / 111_195.0   # degrees of latitude per metre (spherical Earth, R=6,371,008.8 m)


def pt(sid, north_m=0.0, east_m=0.0):
    return (sid, 28.6 + north_m * DLAT_M, 77.2 + east_m * DLAT_M / 0.8777)


# --- normalisation ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("a,b", [("Vaishali  Enclave / Kapil Vihar", "Vaishali Enclave / Kapil Vihar"), ("KIRODI MAL COLLEGE", "Kirodi Mal College"),
                                 ("Nangloi Depot  / Jwala Puri", "Nangloi Depot /  Jwala Puri"), ("Ａlpha　Gate", "alpha gate"),
                                 ("Saket A block(Malviya Nagar)", "saket a block malviya nagar"), ("  X  ", "x")])
def test_normalisation_merges_cosmetic_variants(a, b):
    assert normalise(a) == normalise(b)


def test_normalisation_does_not_destroy_other_scripts_or_distinct_names():
    assert normalise("कश्मीरी गेट") == "कश्मीरी गेट"                      # combining marks preserved
    assert normalise("Nangloi") != normalise("Nangloi Metro Station")
    assert normalise(None) == "" and normalise("   ") == "" and normalise("---") == ""


# --- cluster rule -------------------------------------------------------------------------------------------------------
def groups(stops, thr=150.0):
    return sorted(sorted(g) for g in cluster_stops(stops, thr))


def test_merge_within_threshold_and_boundary_is_inclusive():
    assert groups([pt("A"), pt("B", 80)]) == [["A", "B"]]
    a, b = pt("A"), pt("B", 149.0)
    assert haversine_m(a[1], a[2], b[1], b[2]) < 150 and groups([a, b]) == [["A", "B"]]
    assert groups([a, pt("C", 151.5)]) == [["A"], ["C"]]


def test_no_merge_beyond_threshold():
    assert groups([pt("A"), pt("B", 400)]) == [["A"], ["B"]]


def test_complete_linkage_blocks_chaining_and_is_deterministic():
    chain = [pt("C1"), pt("C2", 100), pt("C3", 200)]          # C1-C2 100 m, C2-C3 100 m, C1-C3 200 m
    expected = [["C1", "C2"], ["C3"]]
    assert groups(chain) == expected
    for seed in range(20):                                      # independent of input order
        shuffled = chain[:]; random.Random(seed).shuffle(shuffled)
        assert groups(shuffled) == expected
    for g in groups(chain):                                     # no cluster ever spans more than the threshold
        pts = [s for s in chain if s[0] in g]
        assert max((haversine_m(a[1], a[2], b[1], b[2]) for a in pts for b in pts), default=0) <= 150


def test_cluster_id_is_a_stable_hash_of_sorted_members():
    assert cluster_id_for(["B", "A"]) == cluster_id_for(["A", "B"]) and cluster_id_for(["A"]) != cluster_id_for(["A", "B"])
    assert cluster_id_for(["A", "B"]).startswith("c_") and len(cluster_id_for(["A", "B"])) == 14


# --- end to end on a database ---------------------------------------------------------------------------------------------
def _feed(headsign: str | None = None) -> dict[str, str]:
    s = [("A1", "Alpha Gate", *pt("x", 0, 0)[1:]), ("A2", "alpha  gate", *pt("x", 78, 0)[1:]), ("A3", "Alpha Gate", *pt("x", 400, 0)[1:]),
         ("B1", "Beta", *pt("x", 0, 2000)[1:]), ("B2", "Beta Metro Station", *pt("x", 20, 2000)[1:]),
         ("C1", "Chain", *pt("x", 0, 4000)[1:]), ("C2", "Chain", *pt("x", 100, 4000)[1:]), ("C3", "Chain", *pt("x", 200, 4000)[1:]),
         ("D1", "Dee", *pt("x", 0, 6000)[1:]), ("D2", "Dee", *pt("x", 5, 6000)[1:])]
    th = ",trip_headsign" if headsign else ""
    return {"stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(f"{a},{b},{c:.7f},{d:.7f}\n" for a, b, c, d in s),
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR1,10UP,10UP,3\nR2,10DOWN,10DOWN,3\n",
            "trips.txt": f"route_id,service_id,trip_id{th}\n" + (f"R1,S1,T1,{headsign}\nR2,S1,T2,\n" if headsign else "R1,S1,T1\nR2,S1,T2\n"),
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,A1,1\nT1,08:10:00,08:10:00,B1,2\nT1,08:20:00,08:20:00,C1,3\n"
                              "T2,09:00:00,09:00:00,A2,1\nT2,09:10:00,09:10:00,A3,2\nT2,09:20:00,09:20:00,C2,3\nT2,09:30:00,09:30:00,B2,4\nT2,09:40:00,09:40:00,C3,5\n"
                              "T2,09:50:00,09:50:00,D1,6\nT2,10:00:00,10:00:00,D2,7\n",
            "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS1,1,1,1,1,1,1,1,20250101,20401231\n"}


def make(tmp_path, headsign=None, derived=True):
    s = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(tmp_path / "c.sqlite3"), "GTFS_ZIP": str(tmp_path / "f.zip")})
    import_gtfs(build_zip(tmp_path / "f.zip", base=_feed(headsign)), s.database_path, promote_retries=0)
    if derived:
        build_derived(s.database_path)
    return TestClient(create_app(s), raise_server_exceptions=False), s.database_path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return make(tmp_path_factory.mktemp("cl"))


def members_of(db):
    c = sqlite3.connect(db)
    rows = c.execute("select cluster_id, group_concat(stop_id) from (select * from cluster_members order by stop_id) group by cluster_id").fetchall()
    c.close()
    return sorted(r[1] for r in rows)


def test_database_clusters_follow_the_rules(built):
    _, db = built
    got = members_of(db)
    assert "A1,A2" in got                       # same normalised name ('alpha  gate' == 'Alpha Gate'), 78 m
    assert "A3" in got                          # same name, 400 m away: separate
    assert "B1" in got and "B2" in got          # 'Beta' vs 'Beta Metro Station' are NOT merged (suffix variants are unsafe)
    assert "C1,C2" in got and "C3" in got       # complete linkage
    assert "D1,D2" in got                       # (D1/D2 are blanked in test_nameless_stops_never_merge)
    assert sorted(x for g in got for x in g.split(",")) == sorted(["A1", "A2", "A3", "B1", "B2", "C1", "C2", "C3", "D1", "D2"])


def test_nameless_stops_never_merge(tmp_path):
    """The importer rejects empty stop_name, so this guards the build script against a database edited after import."""
    _, db = make(tmp_path, derived=False)
    c = sqlite3.connect(db); c.execute("UPDATE stops SET stop_name = '' WHERE stop_id = 'D1'"); c.execute("UPDATE stops SET stop_name = NULL WHERE stop_id = 'D2'")
    c.commit(); c.close()
    build_derived(db)
    got = members_of(db)
    assert "D1" in got and "D2" in got and "D1,D2" not in got


def test_cluster_endpoint_contract(built):
    client, db = built
    cid = client.get(f"{V}/stops/A1").json()["cluster_id"]
    j = client.get(f"{V}/clusters/{cid}").json()
    assert j["cluster_id"] == cid and j["stop_count"] == 2 and j["display_name"] == "Alpha Gate"      # most frequent spelling, whitespace-collapsed
    assert j["threshold_m"] == 150.0 and j["rule"] and j["headsigns_available"] is False and "choose the specific stop" in j["notice"]
    m = {x["stop_id"]: x for x in j["members"]}
    assert set(m) == {"A1", "A2"} and all(x["headsigns"] == [] for x in m.values())                    # nothing invented
    assert m["A1"]["route_names"] == ["10UP"] and m["A2"]["route_names"] == ["10DOWN"] and m["A1"]["scheduled_calls"] == 1
    assert m["A1"]["compass"] == "S" and m["A2"]["compass"] == "N"                                      # A2 is north of A1: bearings from the centroid
    assert abs(m["A1"]["distance_from_centroid_m"] - 39) <= 1 and abs(m["A2"]["distance_from_centroid_m"] - 39) <= 1
    single = client.get(f"{V}/clusters/{client.get(f'{V}/stops/A3').json()['cluster_id']}").json()["members"][0]
    assert single["bearing_from_centroid_deg"] is None and single["compass"] is None and single["distance_from_centroid_m"] == 0


def test_cluster_errors(built, tmp_path):
    client, _ = built
    assert client.get(f"{V}/clusters/c_nope").status_code == 404
    assert client.get(f"{V}/clusters/c_nope").json()["error"]["code"] == "cluster_not_found"
    bare, _ = make(tmp_path, derived=False)
    r = bare.get(f"{V}/clusters/c_x")
    assert r.status_code == 503 and r.json()["error"]["code"] == "derived_data_missing"


def test_cluster_id_is_additive_and_omitted_when_unbuilt(built, tmp_path):
    client, _ = built
    assert client.get(f"{V}/stops/A1").json()["cluster_id"].startswith("c_")
    assert all(i["cluster_id"].startswith("c_") for i in client.get(f"{V}/stops", params={"q": "alpha"}).json()["items"])
    bare, _ = make(tmp_path, derived=False)
    assert "cluster_id" not in bare.get(f"{V}/stops/A1").json()
    assert all("cluster_id" not in i for i in bare.get(f"{V}/stops", params={"q": "alpha"}).json()["items"])


def test_headsigns_appear_only_when_the_feed_has_them(tmp_path):
    client, _ = make(tmp_path, headsign="Anand Vihar")
    cid = client.get(f"{V}/stops/A1").json()["cluster_id"]
    j = client.get(f"{V}/clusters/{cid}").json()
    m = {x["stop_id"]: x for x in j["members"]}
    assert j["headsigns_available"] is True and m["A1"]["headsigns"] == ["Anand Vihar"] and m["A2"]["headsigns"] == []   # A2 is only on T2 (no headsign)
