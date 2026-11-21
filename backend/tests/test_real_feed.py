"""Optional: import the REAL Delhi feed into a temporary database and check it end to end.

    $env:CROWDSENSE_REAL_FEED_ZIP = "data\\delhi_buses_static_gtfs_v1.zip"
    python -m pytest -m real_feed -v

Never touches ``data/crowdsense.sqlite3``: the database is built inside pytest's temporary directory.
The expected numbers are *measured facts about this particular feed* (delhi_buses_static_gtfs_v1); if the feed
is replaced these assertions are meant to fail loudly so the change is looked at.
"""

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gtfs.importer import import_gtfs
from app.main import create_app

ZIP = os.environ.get("CROWDSENSE_REAL_FEED_ZIP")
pytestmark = [pytest.mark.real_feed, pytest.mark.skipif(not ZIP, reason="CROWDSENSE_REAL_FEED_ZIP not set")]
V = "/api/v1"


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("real")
    db = tmp / "real.sqlite3"
    report = import_gtfs(Path(ZIP), db, promote_retries=0)
    settings = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(db)})
    return report, db, TestClient(create_app(settings), raise_server_exceptions=False)


def test_real_delhi_feed_imports_with_known_counts(real):
    report, _, _ = real
    assert report.counts == {"stops": 6812, "routes": 2554, "trips": 65322, "stop_times": 2385381,
                             "calendar": 1, "calendar_dates": 0}


def test_every_table_count(real):
    report, _, _ = real
    assert report.table_counts == {
        "agency": 2, "stops": 6812, "levels": 0, "routes": 2554, "trips": 65322, "calendar": 1, "calendar_dates": 0,
        "shapes": 2554, "shape_points": 765633, "stop_times": 2385381, "frequencies": 0, "transfers": 0, "pathways": 0,
        "attributions": 0, "fare_attributes": 0, "fare_rules": 0, "feed_info": 2}
    assert all(d["rows_rejected"] == 0 and d["rows_read"] == d["rows_imported"] for d in report.file_details)


def test_data_quality_has_no_errors_and_the_known_findings(real):
    report, _, _ = real
    dq = report.data_quality
    assert dq["status"] == "pass_with_warnings" and dq["error_count"] == 0
    warnings = {f["code"] for f in dq["findings"] if f["severity"] == "warning"}
    assert warnings == {"feed_info_multiple_rows", "consecutive_duplicate_stop"}
    failed = {c["code"] for c in dq["integrity_checks"] if c["status"] == "failed"}
    assert failed == {"consecutive_duplicate_stop"}
    by_code = {c["code"]: c["status"] for c in dq["integrity_checks"]}
    for code in ("stop_time_trip_missing", "stop_time_stop_missing", "trip_route_missing", "trip_shape_missing",
                 "trip_service_missing", "route_agency_missing", "time_travel", "trips_without_shape"):
        assert by_code[code] == "passed", code
    infos = {f["code"] for f in dq["findings"] if f["severity"] == "info"}
    assert {"overnight_service", "extension_column_stored", "extension_column_empty"} <= infos


def test_calendar_is_one_weekly_service_without_exceptions(real):
    _, _, api = real
    s = api.get(f"{V}/gtfs/summary").json()
    assert s["calendar"]["services_in_calendar"] == 1 and s["calendar"]["exception_rows"] == 0
    assert s["calendar"]["calendar_dates_present"] is False
    assert (s["calendar"]["first_start_date"], s["calendar"]["last_end_date"]) == ("20250101", "20400101")
    assert api.get(f"{V}/services/active", params={"date": "2026-11-08"}).json()["active_service_ids"] == ["1"]  # Sunday
    assert api.get(f"{V}/services/active", params={"date": "2026-11-09"}).json()["active_service_ids"] == ["1"]  # Monday
    assert api.get(f"{V}/services/active", params={"date": "2040-01-02"}).json()["active_service_ids"] == []
    assert api.get(f"{V}/services/active", params={"date": "2024-12-31"}).json()["active_service_ids"] == []


def test_summary_and_agencies(real):
    _, _, api = real
    s = api.get(f"{V}/gtfs/summary").json()
    assert s["shapes"] == {"shape_count": 2554, "point_count": 765633, "min_points_per_shape": 6, "max_points_per_shape": 1501,
                           "trips_with_shape": 65322, "trips_total": 65322}
    assert s["routes_by_type"] == {"3": 2554}
    assert [a["agency_id"] for a in api.get(f"{V}/agencies").json()["items"]] == ["DTC", "DOT"]


def test_actual_route_geometry_is_queryable(real):
    _, _, api = real
    shape = api.get(f"{V}/trips/1_06_05/shape").json()
    assert shape["shape_available"] and shape["geometry_source"] == "gtfs_shape" and shape["shape_id"] == "shp_3_2029"
    assert shape["returned_points"] == shape["point_count"] and shape["point_count"] > 100
    seq = [p["sequence"] for p in shape["points"]]
    assert seq == sorted(seq) and len(set(seq)) == len(seq)
    lats = [p["lat"] for p in shape["points"]]
    assert 28.0 < min(lats) and max(lats) < 29.5  # Delhi region, as in the feed
    gj = api.get(f"{V}/trips/1_06_05/shape", params={"format": "geojson"}).json()["geojson"]
    assert gj["geometry"]["type"] == "LineString" and len(gj["geometry"]["coordinates"]) == shape["point_count"]


def test_trip_route_stop_endpoints(real):
    _, _, api = real
    trip = api.get(f"{V}/trips/1_06_05").json()
    assert trip["route_id"] == "1" and trip["stop_count"] == 36 and trip["first_stop"]["stop_sequence"] == 0
    st = api.get(f"{V}/trips/1_06_05/stop-times", params={"limit": 5}).json()
    assert st["total"] == 36 and len(st["items"]) == 5 and st["items"][0]["stop_name"] == "Rohini Sec 22 Terminal"
    route = api.get(f"{V}/routes/1").json()
    assert route["agency"]["agency_id"] == "DOT" and route["trip_count"] > 0 and route["shapes"][0]["point_count"] > 0
    stop = api.get(f"{V}/stops/115").json()
    assert stop["stop_time_count"] == 4192 and len(stop["routes"]) == 139


def test_departures_after_midnight_use_the_previous_service_day(real):
    _, _, api = real
    items = api.get(f"{V}/stops/115/departures", params={"date": "2026-11-10", "after": "00:00", "limit": 100}).json()["items"]
    overnight = [d for d in items if d["service_date"] == "2026-11-09"]
    assert overnight, "expected trips of the previous service day running past midnight"
    # a 24:xx-27:xx GTFS time of 9 Nov is an early-morning clock time on 10 Nov
    assert all(d["departure_time"] >= "24:00:00" and d["departure"].startswith("2026-11-10T0") for d in overnight)


def test_responses_are_bounded_and_queries_use_indexes(real):
    _, db, api = real
    assert api.get(f"{V}/trips/1_06_05/stop-times", params={"limit": 501}).status_code == 422
    assert len(api.get(f"{V}/stops", params={"limit": 50}).json()["items"]) == 50
    c = sqlite3.connect(db)
    plans = {
        "trip stop-times": ("SELECT * FROM stop_times WHERE trip_id = '1_06_05' ORDER BY stop_sequence", ()),
        "stop departures": ("SELECT * FROM stop_times WHERE stop_id = '115' AND departure_time >= '08:00:00' ORDER BY departure_time", ()),
        "shape points": ("SELECT * FROM shape_points WHERE shape_id = 'shp_3_2029' ORDER BY shape_pt_sequence", ()),
        "route trips": ("SELECT * FROM trips WHERE route_id = '1'", ()),
    }
    for name, (sql, params) in plans.items():
        plan = " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, params))
        assert "USING" in plan and not any(w in plan for w in ("SCAN stop_times", "SCAN shape_points", "SCAN trips")), (name, plan)
    c.close()
