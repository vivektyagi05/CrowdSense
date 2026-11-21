import sqlite3

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

J = "/api/v1/journeys"


def get(client, **params):
    base = {"origin_stop_id": "A", "destination_stop_id": "C", "departure": "2026-11-08T07:00:00"}
    return client.get(J, params={**base, **params})


# ----- health ---------------------------------------------------------------

def test_health_ok_reports_all_four_components(client):
    r = client.get("/api/v1/health")
    b = r.json()
    assert r.status_code == 200 and b["status"] == "ok"
    assert b["checks"]["application"]["status"] == "ok"
    assert b["checks"]["database"]["status"] == "ok"
    assert b["checks"]["gtfs"]["status"] == "ready" and b["checks"]["gtfs"]["counts"]["stop_times"] == 10
    assert b["checks"]["crowd_engine"]["status"] == "not_connected"
    # legacy fields preserved
    assert b["gtfs_loaded"] is True and b["crowd_engine"] == "not_connected"
    assert b["counts"] == {"stops": 4, "routes": 2, "trips": 4, "stop_times": 10}
    assert b["checks"]["gtfs"]["last_import_attempt"]["status"] == "success"


def test_health_missing_database_is_503_without_leaking_paths(empty_client, settings):
    r = empty_client.get("/api/v1/health")
    b = r.json()
    assert r.status_code == 503 and b["status"] == "needs_setup" and b["gtfs_loaded"] is False
    assert b["checks"]["database"]["status"] == "missing" and b["checks"]["application"]["status"] == "ok"
    assert str(settings.database_path.parent) not in r.text and "Traceback" not in r.text
    assert not settings.database_path.exists()  # health never creates the DB


def test_health_empty_tables_not_ready(settings):
    from app.gtfs.schema import TABLES_DDL
    settings.database_path.parent.mkdir(parents=True)
    c = sqlite3.connect(settings.database_path)
    for stmt in TABLES_DDL.split(";"):
        if stmt.strip():
            c.execute(stmt)
    c.commit()
    c.close()
    r = TestClient(create_app(settings)).get("/api/v1/health")
    assert r.status_code == 503 and r.json()["checks"]["gtfs"]["status"] == "not_ready"
    assert r.json()["checks"]["database"]["status"] == "ok"


def test_health_missing_tables_not_ready(settings):
    settings.database_path.parent.mkdir(parents=True)
    sqlite3.connect(settings.database_path).execute("CREATE TABLE x(a)").connection.close()
    r = TestClient(create_app(settings)).get("/api/v1/health")
    assert r.status_code == 503 and "table 'stops' is missing" in r.json()["checks"]["gtfs"]["problems"]


def test_health_corrupt_database_is_error_not_leaky(settings):
    settings.database_path.parent.mkdir(parents=True)
    settings.database_path.write_bytes(b"garbage" * 1000)
    r = TestClient(create_app(settings)).get("/api/v1/health")
    assert r.status_code == 503 and r.json()["status"] == "error"
    assert "garbage" not in r.text and "not a usable" not in r.text


def test_liveness_ok_even_without_database(empty_client):
    r = empty_client.get("/api/v1/health/live")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_health_surfaces_failed_last_import_but_stays_ok(client, imported, tmp_path):
    from app.gtfs.errors import GtfsDataError
    from app.gtfs.importer import import_gtfs
    from tests.gtfs_factory import build_zip
    try:
        import_gtfs(build_zip(tmp_path / "bad.zip", overrides={"stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,x,999,0\n"}),
                    imported.database_path, promote_retries=0)
    except GtfsDataError:
        pass
    b = client.get("/api/v1/health").json()
    assert b["status"] == "ok" and b["checks"]["gtfs"]["last_import_attempt"]["status"] == "failed"
    assert "errors" not in b["checks"]["gtfs"]["last_import_attempt"]


# ----- stops ----------------------------------------------------------------

def test_stop_search_is_case_insensitive_and_ordered(client):
    items = client.get("/api/v1/stops", params={"q": "STOP"}).json()["items"]
    assert [i["stop_id"] for i in items] == ["A", "B", "D", "C"] or [i["stop_name"] for i in items] == sorted(i["stop_name"] for i in items)
    assert set(items[0]) == {"stop_id", "stop_name", "stop_lat", "stop_lon"}


def test_stop_search_limit_and_validation(client):
    assert len(client.get("/api/v1/stops", params={"q": "stop", "limit": 2}).json()["items"]) == 2
    # Phase 1: a missing q is no longer an error (GET /stops now lists stops; see test_api_v1.py).
    for params in ({"q": "a"}, {"q": "  "}, {"q": "stop", "limit": 0}, {"q": "stop", "limit": 51}):
        r = client.get("/api/v1/stops", params=params)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error" and r.json()["detail"]


def test_stop_search_wildcards_are_literal(client):
    assert [i["stop_id"] for i in client.get("/api/v1/stops", params={"q": "50%_"}).json()["items"]] == ["C"]
    assert client.get("/api/v1/stops", params={"q": "A_pha"}).json()["items"] == []
    assert client.get("/api/v1/stops", params={"q": "%%"}).json()["items"] == []


def test_stops_without_database_is_503_and_creates_nothing(empty_client, settings):
    r = empty_client.get("/api/v1/stops", params={"q": "stop"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"
    assert str(settings.database_path) not in r.text and not settings.database_path.exists()


# ----- journeys (existing behaviour) ---------------------------------------

def test_direct_journeys_basic(client):
    b = get(client).json()
    assert b["mode"] == "direct_only" and "Scheduled times only" in b["notice"]
    first = b["items"][0]
    assert first["trip_id"] == "T1" and first["route_name"] == "101"
    assert first["departure"] == "2026-11-08T08:00:00" and first["arrival"] == "2026-11-08T08:20:00"
    assert first["scheduled_duration_minutes"] == 20 and first["intermediate_stops"] == 1
    assert first["origin"] == "Alpha Stop" and first["destination"].startswith("Gamma")
    assert first["data_basis"] == "static GTFS scheduled service"
    assert [i["trip_id"] for i in b["items"]] == ["T1", "T2"]


def test_crowd_is_never_fabricated(client):
    for item in get(client).json()["items"]:
        assert item["crowd"] == {"status": "NOT_AVAILABLE", "label": "Crowd data not connected"}


def test_departure_time_filter_and_limit(client):
    assert [i["trip_id"] for i in get(client, departure="2026-11-08T08:00:01").json()["items"]] == ["T2"]
    assert [i["trip_id"] for i in get(client, departure="2026-11-08T08:00:00").json()["items"]] == ["T1", "T2"]
    assert len(get(client, limit=1).json()["items"]) == 1
    assert get(client, departure="2026-11-08T23:00:00").json()["items"] == []


def test_limit_applies_after_time_filter(client):
    # Regression: the original code limited to the earliest N departures of the day *before*
    # filtering by time, so a late request could return nothing.
    items = get(client, departure="2026-11-08T08:30:00", limit=1).json()["items"]
    assert [i["trip_id"] for i in items] == ["T2"]


def test_extended_gtfs_hours_roll_to_next_day(client):
    items = client.get(J, params={"origin_stop_id": "A", "destination_stop_id": "B", "departure": "2026-11-08T23:00:00"}).json()["items"]
    assert items[0]["trip_id"] == "T3"
    assert items[0]["departure"] == "2026-11-08T23:50:00" and items[0]["arrival"] == "2026-11-09T00:10:00"
    assert items[0]["scheduled_duration_minutes"] == 20


def test_calendar_dates_add_and_remove_service(client):
    added = client.get(J, params={"origin_stop_id": "A", "destination_stop_id": "D", "departure": "2026-11-09T07:00:00"}).json()
    assert [i["trip_id"] for i in added["items"]] == ["T4"]
    other_day = client.get(J, params={"origin_stop_id": "A", "destination_stop_id": "D", "departure": "2026-11-08T07:00:00"}).json()
    assert other_day["items"] == []
    removed = get(client, departure="2026-11-10T07:00:00").json()
    assert removed == {"items": [], "message": "No active GTFS service for this date."}


def test_no_service_outside_calendar_range(client):
    assert get(client, departure="2041-06-01T07:00:00").json()["message"] == "No active GTFS service for this date."


def test_journey_validation_errors(client):
    r = get(client, departure="not-a-date")
    assert r.status_code == 400 and r.json()["detail"].startswith("Use ISO local datetime")
    r = get(client, departure="2026-11-08T08:00:00+05:30")  # used to crash with HTTP 500
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_departure"
    assert get(client, destination_stop_id="A").status_code == 400
    r = get(client, origin_stop_id="NOPE")
    assert r.status_code == 404 and r.json()["error"]["code"] == "stop_not_found"
    assert client.get(J, params={"origin_stop_id": "A"}).status_code == 422
    assert get(client, limit=0).status_code == 422 and get(client, limit=31).status_code == 422


def test_journeys_without_database_is_503(empty_client):
    r = get(empty_client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"


# ----- error handling / config ---------------------------------------------

def test_unhandled_errors_are_generic(imported, monkeypatch):
    from app.api import stops as stops_api
    monkeypatch.setattr(stops_api, "search_stops", lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("internal secret")))
    r = TestClient(create_app(imported), raise_server_exceptions=False).get("/api/v1/stops", params={"q": "stop"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text and "ZeroDivision" not in r.text


def test_unknown_route_uses_structured_error(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_cors_allows_configured_origin_only(tmp_path):
    s = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(tmp_path / "d.sqlite3"), "CORS_ALLOWED_ORIGINS": "http://ok.test:1234"})
    c = TestClient(create_app(s))
    ok = c.get("/api/v1/health/live", headers={"Origin": "http://ok.test:1234"})
    bad = c.get("/api/v1/health/live", headers={"Origin": "http://evil.test"})
    assert ok.headers.get("access-control-allow-origin") == "http://ok.test:1234"
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-credentials" not in ok.headers


def test_connections_are_closed_after_requests(client, imported):
    for _ in range(20):
        client.get("/api/v1/stops", params={"q": "stop"})
    import os
    sidecars = [p for p in os.listdir(imported.database_path.parent) if p.endswith(("-wal", "-shm"))]
    assert sidecars == []  # last connection closed -> SQLite removed its WAL/SHM
