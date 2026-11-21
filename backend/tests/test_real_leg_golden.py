"""Phase 4 / M3 golden tests on the REAL Delhi database (read-only). Skipped when the DB has not been imported."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.main import create_app

REAL_DB = BASE_DIR / "data" / "crowdsense.sqlite3"
pytestmark = pytest.mark.skipif(not REAL_DB.exists(), reason="real database not imported (python -m scripts.import_gtfs)")
V = "/api/v1"
LOOP_TRIP = "2716_04_50"          # longest shape in the feed (1,501 points); starts and ends at ISBT Anand Vihar (stop 4947)


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Settings.from_env({"APP_ENV": "test"})), raise_server_exceptions=False)


@pytest.fixture(scope="module")
def calls():
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    rows = c.execute("select stop_id, departure_time from stop_times where trip_id=? order by stop_sequence", (LOOP_TRIP,)).fetchall()
    c.close()
    return rows


def test_real_loop_whole_trip(client, calls):
    j = client.get(f"{V}/trips/{LOOP_TRIP}/shape", params=dict(from_stop_id=calls[0][0], to_stop_id=calls[-1][0], board=calls[0][1])).json()
    assert calls[0][0] == calls[-1][0] == "4947"
    assert j["status"] == "ok" and j["match_method"] == "projection"          # feed has no stop_times.shape_dist_traveled
    assert j["length_m"] == pytest.approx(106_522.6, rel=0.01)                 # measured 2026-11-13 (EVIDENCE.md M3)
    assert j["point_count_returned"] < j["point_count_original"] <= 1501 and j["boarding"]["distance_to_shape_m"] < 5


def test_real_mid_leg_is_a_strict_part_of_the_loop(client, calls):
    j = client.get(f"{V}/trips/{LOOP_TRIP}/shape", params=dict(from_stop_id=calls[40][0], to_stop_id=calls[120][0], board=calls[40][1])).json()
    assert j["status"] == "ok" and j["length_m"] == pytest.approx(41_461.1, rel=0.01)
    assert j["coordinates"][0] != j["coordinates"][-1]


def test_real_stop_not_on_trip(client):
    r = client.get(f"{V}/trips/{LOOP_TRIP}/shape", params=dict(from_stop_id="4947", to_stop_id="definitely-not-a-stop"))
    assert r.status_code == 404 and r.json()["error"]["code"] == "stop_not_on_trip"


def test_real_feed_has_no_no_shape_trips_and_no_stop_time_distances():
    """Documents WHY those branches are covered by synthetic fixtures: the real feed never exercises them."""
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    assert c.execute("select count(*) from trips where shape_id is null").fetchone()[0] == 0
    assert c.execute("select count(*) from stop_times where shape_dist_traveled is not null").fetchone()[0] == 0
    c.close()


def test_every_real_route_projects_monotonically():
    from app.geo.planar import Plane, PolylineIndex, monotone_match
    from app.services.leg_service import _load_calls, _load_shape
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    bad = 0
    for t in c.execute("select min(trip_id) trip_id, shape_id from trips group by route_id").fetchall()[::10]:   # every 10th route: ~256
        pts, cl = _load_shape(c, t["shape_id"]), _load_calls(c, t["trip_id"])
        plane = Plane.around([(p[0], p[1]) for p in pts]); line = [plane.to_xy(p[0], p[1]) for p in pts]
        m = monotone_match(PolylineIndex(line, 60.0), [plane.to_xy(x["stop_lon"], x["stop_lat"]) for x in cl], 60.0)
        along = [x.along_m for x in m if x]
        bad += any(b < a - 1.0 for a, b in zip(along, along[1:]))
    c.close()
    assert bad == 0
