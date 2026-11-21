"""Phase 1 GTFS query API, against a database built from the complete synthetic feed (tests/gtfs_full.py)."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.gtfs_full import FULL_COUNTS

V = "/api/v1"


def ids(items, key="stop_id"):
    return [i[key] for i in items]


# --- agencies -------------------------------------------------------------------------------------------

def test_agencies(full_client):
    b = full_client.get(f"{V}/agencies").json()
    assert b["total"] == 2 and ids(b["items"], "agency_id") == ["AG1", "AG2"]  # ordered by name
    assert b["items"][0]["agency_timezone"] == "Asia/Kolkata"


# --- stops: list / filter / paginate -----------------------------------------------------------------------

def test_stops_list_without_q_is_paginated_and_ordered(full_client):
    b = full_client.get(f"{V}/stops").json()
    assert b["total"] == 4 and b["limit"] == 20 and b["offset"] == 0
    assert ids(b["items"]) == ["A", "B", "D", "C"]  # by name: Alpha, Beta, Delta, Gamma
    page = full_client.get(f"{V}/stops", params={"limit": 1, "offset": 2}).json()
    assert ids(page["items"]) == ["D"] and page["total"] == 4
    assert full_client.get(f"{V}/stops", params={"offset": 10}).json()["items"] == []


def test_stops_bbox_and_route_filters_combine(full_client):
    assert ids(full_client.get(f"{V}/stops", params={"bbox": "77.205,28.605,77.215,28.615"}).json()["items"]) == ["B"]
    assert ids(full_client.get(f"{V}/stops", params={"route_id": "R2"}).json()["items"]) == ["A", "B"]
    both = full_client.get(f"{V}/stops", params={"route_id": "R1", "q": "gamma"}).json()
    assert ids(both["items"]) == ["C"] and both["total"] == 1


def test_stops_filter_validation(full_client):
    assert full_client.get(f"{V}/stops", params={"route_id": "NOPE"}).json()["error"]["code"] == "route_not_found"
    for bad in ({"bbox": "1,2,3"}, {"bbox": "a,b,c,d"}, {"bbox": "80,0,70,10"}, {"offset": -1}):
        r = full_client.get(f"{V}/stops", params=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", bad


def test_stop_detail_lists_serving_routes_in_one_response(full_client):
    b = full_client.get(f"{V}/stops/A").json()
    assert b["stop_name"] == "Alpha Stop" and b["stop_code"] == "CA" and b["stop_time_count"] == 4
    assert [(r["route_id"], r["stop_time_count"]) for r in b["routes"]] == [("R1", 3), ("R2", 1)]
    assert full_client.get(f"{V}/stops/ZZZ").json()["error"]["code"] == "stop_not_found"


def test_stop_ids_with_special_characters_round_trip(full_client):
    assert full_client.get(f"{V}/stops/C").json()["stop_name"] == "Gamma 50%_Stop"


# --- departures (service days, overnight) ------------------------------------------------------------------

def test_departures_include_previous_service_days_overnight_trips(full_client):
    b = full_client.get(f"{V}/stops/B/departures", params={"date": "2026-11-08", "limit": 3}).json()
    first = b["items"][0]
    # T3 started at 23:50 on 7 Nov; its 24:10:00 call at B is 00:10 on 8 Nov
    assert (first["trip_id"], first["service_date"], first["departure_time"], first["departure"]) == \
           ("T3", "2026-11-07", "24:10:00", "2026-11-08T00:10:00")
    assert [(d["trip_id"], d["departure"]) for d in b["items"][1:]] == [("T1", "2026-11-08T08:10:00"), ("T2", "2026-11-08T09:10:00")]
    assert "not live predictions" in b["notice"]


def test_departures_after_filter_and_service_exceptions(full_client):
    late = full_client.get(f"{V}/stops/B/departures", params={"date": "2026-11-08", "after": "23:00"}).json()["items"]
    assert [(d["trip_id"], d["service_date"], d["departure"]) for d in late] == [("T3", "2026-11-08", "2026-11-09T00:10:00")]
    added = full_client.get(f"{V}/stops/D/departures", params={"date": "2026-11-09"}).json()["items"]
    assert ids(added, "trip_id") == ["T4"]  # S2 only exists through calendar_dates
    assert full_client.get(f"{V}/stops/D/departures", params={"date": "2026-11-08"}).json()["items"] == []
    # S1 removed on 10 Nov: nothing runs that day except the previous day's overnight T3 at B
    tue = full_client.get(f"{V}/stops/A/departures", params={"date": "2026-11-10"}).json()["items"]
    assert tue == []


def test_departures_validation(full_client):
    assert full_client.get(f"{V}/stops/NOPE/departures", params={"date": "2026-11-08"}).status_code == 404
    assert full_client.get(f"{V}/stops/A/departures", params={"date": "08-11-2026"}).status_code == 422
    assert full_client.get(f"{V}/stops/A/departures", params={"date": "2026-11-08", "limit": 101}).status_code == 422


# --- routes ------------------------------------------------------------------------------------------------

def test_routes_filters_and_pagination(full_client):
    b = full_client.get(f"{V}/routes").json()
    assert b["total"] == 2 and ids(b["items"], "route_id") == ["R1", "R2"]  # 101 < NIGHT
    assert ids(full_client.get(f"{V}/routes", params={"q": "night"}).json()["items"], "route_id") == ["R2"]
    assert ids(full_client.get(f"{V}/routes", params={"q": "alpha to"}).json()["items"], "route_id") == ["R1"]
    assert ids(full_client.get(f"{V}/routes", params={"agency_id": "AG1"}).json()["items"], "route_id") == ["R1"]
    assert full_client.get(f"{V}/routes", params={"route_type": 3}).json()["total"] == 2
    assert full_client.get(f"{V}/routes", params={"route_type": 700}).json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert ids(full_client.get(f"{V}/routes", params={"limit": 1, "offset": 1}).json()["items"], "route_id") == ["R2"]
    assert full_client.get(f"{V}/routes", params={"limit": 201}).status_code == 422


def test_route_detail(full_client):
    r1 = full_client.get(f"{V}/routes/R1").json()
    assert (r1["trip_count"], r1["stop_count"], r1["service_ids"], r1["directions"]) == (3, 4, ["S1", "S2"], {"0": 3})
    assert r1["agency"]["agency_name"] == "Alpha Transit" and r1["route_desc"] == "Express"
    assert [(s["shape_id"], s["trip_count"], s["point_count"]) for s in r1["shapes"]] == [("SH1", 2, 3), ("SH2", 1, 2)]
    r2 = full_client.get(f"{V}/routes/R2").json()
    assert r2["shapes"] == [{"shape_id": None, "trip_count": 1, "point_count": None}] and r2["directions"] == {"1": 1}
    assert full_client.get(f"{V}/routes/NOPE").json()["error"]["code"] == "route_not_found"


def test_route_trips_ordered_by_first_departure_with_filters(full_client):
    b = full_client.get(f"{V}/routes/R1/trips", params={"limit": 2}).json()
    assert b["total"] == 3 and [(t["trip_id"], t["first_departure"]) for t in b["items"]] == [("T1", "08:00:00"), ("T2", "09:00:00")]
    assert ids(full_client.get(f"{V}/routes/R1/trips", params={"offset": 2}).json()["items"], "trip_id") == ["T4"]
    assert ids(full_client.get(f"{V}/routes/R1/trips", params={"service_id": "S2"}).json()["items"], "trip_id") == ["T4"]
    assert full_client.get(f"{V}/routes/NOPE/trips").status_code == 404


# --- trips & stop times ---------------------------------------------------------------------------------------

def test_trip_detail(full_client):
    t1 = full_client.get(f"{V}/trips/T1").json()
    assert (t1["stop_count"], t1["has_shape"], t1["shape_id"], t1["route_short_name"]) == (3, True, "SH1", "101")
    assert t1["first_stop"] == {"stop_id": "A", "stop_name": "Alpha Stop", "stop_sequence": 1, "time": "08:00:00"}
    assert t1["last_stop"]["stop_id"] == "C" and t1["last_stop"]["time"] == "08:20:00"
    assert full_client.get(f"{V}/trips/T3").json()["has_shape"] is False
    assert full_client.get(f"{V}/trips/NOPE").json()["error"]["code"] == "trip_not_found"


def test_trip_stop_times_are_ordered_by_sequence_and_paginated(full_client):
    full = full_client.get(f"{V}/trips/T2/stop-times").json()
    assert [i["stop_sequence"] for i in full["items"]] == [1, 5, 9] and full["total"] == 3  # sparse sequences kept as given
    first = full["items"][0]
    assert (first["stop_name"], first["arrival_time"], first["timepoint"], first["fare_stage"]) == ("Alpha Stop", "09:00:00", 1, 0)
    page = full_client.get(f"{V}/trips/T2/stop-times", params={"limit": 2, "offset": 1}).json()
    assert [i["stop_sequence"] for i in page["items"]] == [5, 9] and page["limit"] == 2 and page["offset"] == 1
    assert full_client.get(f"{V}/trips/T3/stop-times").json()["items"][1]["arrival_time"] == "24:10:00"
    assert full_client.get(f"{V}/trips/T1/stop-times", params={"limit": 501}).status_code == 422
    assert full_client.get(f"{V}/trips/NOPE/stop-times").status_code == 404


# --- shapes ---------------------------------------------------------------------------------------------------------

def test_trip_shape_returns_the_actual_points_in_sequence_order(full_client):
    b = full_client.get(f"{V}/trips/T1/shape").json()
    assert b["shape_available"] and b["geometry_source"] == "gtfs_shape" and b["shape_id"] == "SH1" and b["trip_id"] == "T1"
    assert [(p["sequence"], p["lat"], p["lon"], p["dist_traveled"]) for p in b["points"]] == \
           [(1, 28.60, 77.20, 0.0), (2, 28.61, 77.21, 1200.25), (3, 28.62, 77.22, 2500.5)]
    assert b["point_count"] == 3 and b["returned_points"] == 3 and b["bbox"] == [77.20, 28.60, 77.22, 28.62]
    assert b["max_dist_traveled"] == 2500.5 and b["geojson"] is None


def test_shape_geojson_uses_lon_lat_order(full_client):
    b = full_client.get(f"{V}/trips/T1/shape", params={"format": "geojson"}).json()
    assert b["points"] == [] and b["geojson"]["geometry"] == {"type": "LineString", "coordinates": [[77.20, 28.60], [77.21, 28.61], [77.22, 28.62]]}
    assert b["geojson"]["properties"]["geometry_source"] == "gtfs_shape"


def test_shape_pagination_and_lookup_by_id(full_client):
    b = full_client.get(f"{V}/shapes/SH1", params={"limit": 1, "offset": 1}).json()
    assert [p["sequence"] for p in b["points"]] == [2] and b["point_count"] == 3 and b["returned_points"] == 1 and b["trip_id"] is None
    assert full_client.get(f"{V}/shapes/NOPE").json()["error"]["code"] == "shape_not_found"
    assert full_client.get(f"{V}/shapes/SH1", params={"limit": 50001}).status_code == 422


def test_trip_without_shape_is_reported_explicitly_and_never_invented(full_client):
    b = full_client.get(f"{V}/trips/T3/shape").json()
    assert b["shape_available"] is False and b["geometry_source"] == "none" and b["points"] == [] and b["reason"] == "trip_has_no_shape_id"
    assert b["point_count"] == 0 and "fallback=stops" in b["note"]


def test_documented_fallback_is_labelled_as_stop_sequence_not_road_geometry(full_client):
    b = full_client.get(f"{V}/trips/T3/shape", params={"fallback": "stops"}).json()
    assert b["shape_available"] is False and b["geometry_source"] == "stop_sequence_fallback"
    assert [(p["lat"], p["lon"]) for p in b["points"]] == [(28.60, 77.20), (28.61, 77.21)]
    assert "NOT the road geometry" in b["note"] and b["reason"] == "trip_has_no_shape_id"
    gj = full_client.get(f"{V}/trips/T3/shape", params={"fallback": "stops", "format": "geojson"}).json()["geojson"]
    assert gj["properties"]["geometry_source"] == "stop_sequence_fallback"
    # a trip that HAS a shape never gets the fallback, even when asked for
    assert full_client.get(f"{V}/trips/T1/shape", params={"fallback": "stops"}).json()["geometry_source"] == "gtfs_shape"
    assert full_client.get(f"{V}/trips/T1/shape", params={"fallback": "bogus"}).status_code == 422


def test_route_shapes(full_client):
    b = full_client.get(f"{V}/routes/R1/shapes").json()
    assert b["route_id"] == "R1" and [(s["shape_id"], s["trip_count"]) for s in b["items"]] == [("SH1", 2), ("SH2", 1)]


# --- services ------------------------------------------------------------------------------------------------------------

def test_active_services_follow_calendar_and_exceptions(full_client):
    def active(day, **extra):
        return full_client.get(f"{V}/services/active", params={"date": day, **extra}).json()

    sunday = active("2026-11-08")
    assert sunday["active_service_ids"] == ["S1"] and sunday["weekday"] == "sunday" and sunday["date_source"] == "request"
    assert sunday["timezone"] == "Asia/Kolkata" and sunday["calendar_dates_present"] is True
    monday = active("2026-11-09")
    assert monday["active_service_ids"] == ["S1", "S2"]
    assert {s["service_id"]: (s["reason"], s["trip_count"]) for s in monday["services"]} == {"S1": ("weekly_calendar", 3), "S2": ("added_by_exception", 1)}
    tuesday = active("2026-11-10", include_inactive=True)
    assert tuesday["active_service_ids"] == [] and tuesday["inactive_count"] == 2
    assert {s["service_id"]: s["reason"] for s in tuesday["services"]} == {"S1": "removed_by_exception", "S2": "not_added_on_this_date"}
    assert active("2026-11-10")["services"] == []  # inactive ones are only listed on request
    assert active("2041-01-05")["active_service_ids"] == []  # beyond the calendar range


def test_active_services_defaults_to_today_in_the_feed_timezone(full_client):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Asia/Kolkata")
    except Exception:
        pytest.skip("timezone database unavailable")
    b = full_client.get(f"{V}/services/active").json()
    assert b["date_source"] == "today_in_feed_timezone" and len(b["date"]) == 10
    assert full_client.get(f"{V}/services/active", params={"date": "2026-13-45"}).status_code == 422


# --- summary & validation report --------------------------------------------------------------------------------------------

def test_summary_reports_actual_counts_and_scope(full_client):
    b = full_client.get(f"{V}/gtfs/summary").json()
    assert b["counts"] == FULL_COUNTS and b["schema_version"] == 2
    assert b["feed"][0]["feed_version"] == "v7" and [a["agency_id"] for a in b["agencies"]] == ["AG1", "AG2"]
    assert b["bounds"] == {"min_lat": 28.6, "min_lon": 77.2, "max_lat": 28.63, "max_lon": 77.23}
    assert b["routes_by_type"] == {"3": 2}
    assert b["calendar"]["services_in_calendar"] == 1 and b["calendar"]["added_exceptions"] == 1 and b["calendar"]["removed_exceptions"] == 1
    assert b["calendar"]["trips_by_service"] == {"S1": 3, "S2": 1}
    assert b["shapes"] == {"shape_count": 2, "point_count": 5, "min_points_per_shape": 2, "max_points_per_shape": 3,
                           "trips_with_shape": 3, "trips_total": 4}
    assert b["data_quality"]["status"] == "pass_with_warnings" and b["data_quality"]["error_count"] == 0
    assert "NOT included" in b["data_scope"]["live_crowd_information"] and "NOT included" in b["data_scope"]["actual_vehicle_operations"]


def test_validation_report_separates_data_quality_from_import_status(full_client, full_settings, tmp_path):
    from app.gtfs.errors import GtfsDataError
    from app.gtfs.importer import import_gtfs
    from tests.gtfs_factory import build_zip
    b = full_client.get(f"{V}/gtfs/validation-report").json()
    assert b["data_quality"]["status"] == "pass_with_warnings" and b["last_import_attempt"]["status"] == "success"
    assert any(c["code"] == "trip_route_missing" and c["status"] == "passed" for c in b["data_quality"]["integrity_checks"])
    assert {f["file"] for f in b["files"]} >= {"shapes.txt", "agency.txt", "stop_times.txt"} and b["missing_optional_files"] == []
    assert b["column_usage"]["stop_times"]["fare_stage"] == 10
    # a later FAILED import changes the attempt record but not the data-quality report of the served database
    with pytest.raises(GtfsDataError):
        import_gtfs(build_zip(tmp_path / "bad.zip", overrides={"stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,x,999,0\n"}),
                    full_settings.database_path, promote_retries=0)
    again = full_client.get(f"{V}/gtfs/validation-report").json()
    assert again["last_import_attempt"]["status"] == "failed"
    assert again["data_quality"] == b["data_quality"] and again["imported_at"] == b["imported_at"]
    assert "errors" not in again["last_import_attempt"]  # row-level details and paths stay out of the API


# --- base feed (no optional files) and outdated databases ------------------------------------------------------------------

def test_endpoints_work_on_a_feed_without_optional_files(client):
    assert client.get(f"{V}/agencies").json() == {"items": [], "total": 0}
    assert client.get(f"{V}/trips/T1/shape").json()["reason"] == "trip_has_no_shape_id"
    s = client.get(f"{V}/gtfs/summary").json()
    assert s["shapes"]["shape_count"] == 0 and s["feed"] == [] and s["counts"]["agency"] == 0
    assert client.get(f"{V}/routes/R1").json()["agency"] is None
    assert client.get(f"{V}/services/active", params={"date": "2026-11-09"}).json()["active_service_ids"] == ["S1", "S2"]


def test_phase0_database_still_serves_phase0_endpoints_but_phase1_says_why_not(full_settings, full_zip):
    from app.gtfs.importer import import_gtfs
    import_gtfs(full_zip, full_settings.database_path, promote_retries=0)
    c = sqlite3.connect(full_settings.database_path)
    c.execute("PRAGMA user_version = 1")
    c.close()
    api = TestClient(create_app(full_settings), raise_server_exceptions=False)
    assert api.get(f"{V}/stops", params={"q": "alpha"}).status_code == 200  # Phase 0 endpoints are unaffected
    assert api.get(f"{V}/health").status_code == 200
    for path in ("/agencies", "/stops/A", "/routes", "/trips/T1", "/gtfs/summary", "/services/active?date=2026-11-08"):
        r = api.get(V + path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "schema_outdated", path
        assert "python -m scripts.import_gtfs" in r.json()["error"]["message"]


def test_phase1_endpoints_without_database_are_503(empty_client, settings):
    for path in ("/agencies", "/routes", "/trips/T1", "/gtfs/summary", "/gtfs/validation-report"):
        r = empty_client.get(V + path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable", path
    assert not settings.database_path.exists()


def test_phase1_connections_are_closed(full_client, full_settings):
    import os
    for _ in range(10):
        full_client.get(f"{V}/gtfs/summary")
        full_client.get(f"{V}/trips/T1/shape")
    assert [p for p in os.listdir(full_settings.database_path.parent) if p.endswith(("-wal", "-shm"))] == []
