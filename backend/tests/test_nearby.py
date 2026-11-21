"""Phase 4 / M4: /stops/nearby, spatial index, derived-data build idempotence and log privacy (SYNTHETIC random stops)."""
from __future__ import annotations

import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.derived.build import build_derived
from app.geo.planar import haversine_m
from app.gtfs.importer import import_gtfs
from app.main import create_app
from app.services.nearby_service import NCR_BOX, bearing_deg, compass
from tests.gtfs_factory import build_zip

V = "/api/v1"
N_STOPS = 2500


def _feed() -> dict[str, str]:
    rnd = random.Random(2026)
    stops = []
    for i in range(N_STOPS):   # dense cluster around Connaught Place + uniform scatter over the NCR box
        if i % 3 == 0:
            la, lo = 28.6315 + rnd.uniform(-0.02, 0.02), 77.2167 + rnd.uniform(-0.02, 0.02)
        else:
            la, lo = rnd.uniform(28.10, 29.40), rnd.uniform(76.60, 77.70)
        stops.append((f"P{i:04d}", f"Stop {i % 700}", la, lo))
    stop_txt = "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(f"{a},{b},{c:.7f},{d:.7f}\n" for a, b, c, d in stops)
    trips, times = [], []
    for t in range(100):
        trips.append(f"R{t % 10},S1,T{t}\n")
        for k in range(25):
            h = 8 + k // 30; m = (k * 2) % 60
            times.append(f"T{t},{h:02d}:{m:02d}:00,{h:02d}:{m:02d}:00,P{(t * 25 + k) % N_STOPS:04d},{k + 1}\n")
    return {"stops.txt": stop_txt,
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\n" + "".join(f"R{i},{100 + i},Route {i},3\n" for i in range(10)),
            "trips.txt": "route_id,service_id,trip_id\n" + "".join(trips),
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "".join(times),
            "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS1,1,1,1,1,1,1,1,20250101,20401231\n"}


@pytest.fixture(scope="module")
def base_db(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("near")
    s = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(d / "base.sqlite3"), "GTFS_ZIP": str(d / "f.zip")})
    import_gtfs(build_zip(d / "f.zip", base=_feed()), s.database_path, promote_retries=0)
    return s.database_path


def _client(db: Path) -> TestClient:
    return TestClient(create_app(Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(db)})), raise_server_exceptions=False)


@pytest.fixture(scope="module", params=["rtree", "grid", "scan"])
def variant(request, base_db, tmp_path_factory):
    db = tmp_path_factory.mktemp(request.param) / "db.sqlite3"
    db.write_bytes(base_db.read_bytes())
    if request.param != "scan":
        build_derived(db, force_grid=request.param == "grid")
    return request.param, _client(db), db


def _oracle(db: Path, lat, lon, radius, limit):
    import sqlite3
    c = sqlite3.connect(db)
    hits = sorted((haversine_m(lat, lon, la, lo), sid) for sid, la, lo in c.execute("select stop_id, stop_lat, stop_lon from stops"))
    c.close()
    inside = [h for h in hits if h[0] <= radius]
    return len(inside), [sid for _, sid in inside[:limit]], [int(round(d)) for d, _ in inside[:limit]]


def test_matches_brute_force_oracle_on_200_random_points(variant):
    method, client, db = variant
    rnd = random.Random(99)
    nonempty = 0
    for _ in range(200):
        if rnd.random() < 0.6:
            lat, lon = 28.6315 + rnd.uniform(-0.03, 0.03), 77.2167 + rnd.uniform(-0.03, 0.03)
        else:
            lat, lon = rnd.uniform(*[NCR_BOX["min_lat"], NCR_BOX["max_lat"]]), rnd.uniform(NCR_BOX["min_lon"], NCR_BOX["max_lon"])
        radius, limit = rnd.choice([50, 200, 500, 1000, 3000]), rnd.choice([1, 5, 20, 50])
        r = client.get(f"{V}/stops/nearby", params=dict(lat=lat, lon=lon, radius_m=radius, limit=limit))
        assert r.status_code == 200
        j = r.json()
        total, ids, dists = _oracle(db, lat, lon, radius, limit)
        assert j["index"] == method
        assert [i["stop_id"] for i in j["items"]] == ids            # identical set AND order
        assert [i["distance_m"] for i in j["items"]] == dists
        assert j["total_in_radius"] == total and j["returned"] == len(ids)
        nonempty += bool(ids)
    assert nonempty > 60          # the oracle comparison was not vacuous


def test_item_fields_are_real_and_consistent(variant):
    _, client, _ = variant
    j = client.get(f"{V}/stops/nearby", params=dict(lat=28.6315, lon=77.2167, radius_m=1000, limit=10)).json()
    assert j["items"], "expected stops around the dense cluster"
    for it in j["items"]:
        assert isinstance(it["distance_m"], int) and 0 <= it["bearing_deg"] < 360 and it["compass"] == compass(it["bearing_deg"])
        assert it["route_names"] == sorted(set(it["route_names"]), key=it["route_names"].index) and len(it["route_names"]) <= 5
        assert it["routes_count"] >= len(it["route_names"])
        assert abs(it["bearing_deg"] - round(bearing_deg(28.6315, 77.2167, it["stop_lat"], it["stop_lon"])) % 360) <= 1
    assert [i["distance_m"] for i in j["items"]] == sorted(i["distance_m"] for i in j["items"])


def test_compass_points():
    assert [compass(d) for d in (0, 44, 46, 90, 135, 180, 225, 270, 315, 359)] == ["N", "NE", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    assert bearing_deg(28.6, 77.2, 28.7, 77.2) == pytest.approx(0, abs=0.01) and bearing_deg(28.6, 77.2, 28.6, 77.3) == pytest.approx(90, abs=0.2)


@pytest.mark.parametrize("params,status,code", [
    (dict(lat=28.6, lon=77.2, radius_m=49), 422, "validation_error"),
    (dict(lat=28.6, lon=77.2, radius_m=3001), 422, "validation_error"),
    (dict(lat=28.6, lon=77.2, limit=0), 422, "validation_error"),
    (dict(lat=28.6, lon=77.2, limit=51), 422, "validation_error"),
    (dict(lat="abc", lon=77.2), 422, "validation_error"),
    (dict(lat="nan", lon=77.2), 422, "validation_error"),
    (dict(lat="inf", lon=77.2), 422, "validation_error"),
    (dict(lat=28.6), 422, "validation_error"),
    (dict(lat=19.07, lon=72.87), 422, "location_out_of_area"),          # Mumbai: a clear message, not an empty list
    (dict(lat=27.99, lon=77.2), 422, "location_out_of_area"),
    (dict(lat=28.6, lon=77.81), 422, "location_out_of_area"),
    (dict(lat=0, lon=0), 422, "location_out_of_area"),
])
def test_validation(variant, params, status, code):
    r = variant[1].get(f"{V}/stops/nearby", params=params)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_in_area_but_empty_is_200_not_an_error(variant):
    j = variant[1].get(f"{V}/stops/nearby", params=dict(lat=28.0, lon=77.79, radius_m=50)).json()
    assert j["total_in_radius"] == 0 and j["items"] == []


def test_defaults_and_route_is_not_shadowed_by_stop_id(variant):
    j = variant[1].get(f"{V}/stops/nearby", params=dict(lat=28.6315, lon=77.2167)).json()
    assert j["radius_m"] == 500 and j["limit"] == 20 and j["returned"] <= 20
    assert variant[1].get(f"{V}/stops/P0000").status_code == 200


def test_boundary_values_of_the_box_are_accepted(variant):
    for lat, lon in ((28.0, 76.4), (29.5, 77.8)):
        assert variant[1].get(f"{V}/stops/nearby", params=dict(lat=lat, lon=lon)).status_code == 200


# --- derived-data build ------------------------------------------------------------------------------------------------

def test_build_is_idempotent_and_deterministic(base_db, tmp_path):
    a, b = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    a.write_bytes(base_db.read_bytes()); b.write_bytes(base_db.read_bytes())
    m1 = build_derived(a); m2 = build_derived(a); m3 = build_derived(b)
    assert m1["content_hash"] == m2["content_hash"] == m3["content_hash"]          # twice on one file, and on an independent copy
    assert m1["spatial_method"] == "rtree" and int(m1["stop_count"]) == N_STOPS and m1["built_at"]
    assert build_derived(a, force_grid=True)["spatial_method"] == "grid"           # the fallback is selectable and recorded


def test_build_is_atomic_on_failure(base_db, tmp_path, monkeypatch):
    db = tmp_path / "x.sqlite3"; db.write_bytes(base_db.read_bytes())
    build_derived(db)
    import app.derived.build as b
    monkeypatch.setattr(b, "_canonical_hash", lambda conn: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        build_derived(db)
    import sqlite3
    c = sqlite3.connect(db)                                                          # previous derived data survived the failed rebuild
    assert c.execute("select count(*) from derived_meta").fetchone()[0] > 0 and c.execute("select count(*) from stop_routes").fetchone()[0] > 0
    c.close()


# --- privacy -------------------------------------------------------------------------------------------------------------

def test_redaction_filter_unit():
    from app.logging_config import redact_coordinates
    assert redact_coordinates('GET /api/v1/stops/nearby?lat=28.612345&lon=77.209876&radius_m=500 HTTP/1.1') == \
        'GET /api/v1/stops/nearby?lat=[redacted]&lon=[redacted]&radius_m=500 HTTP/1.1'
    assert redact_coordinates("/stops?q=gate&limit=5") == "/stops?q=gate&limit=5"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def test_real_server_logs_contain_no_coordinates(base_db, tmp_path):
    """Runs the real `python -m app` (uvicorn, default access log) and greps everything it printed."""
    db = tmp_path / "srv.sqlite3"; db.write_bytes(base_db.read_bytes()); build_derived(db)
    port = _free_port()
    env = {**os.environ, "DATABASE_PATH": str(db), "BACKEND_PORT": str(port), "BACKEND_HOST": "127.0.0.1", "APP_ENV": "test",
           "LOG_LEVEL": "DEBUG", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "app"], cwd=BASE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}{V}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        url = f"http://127.0.0.1:{port}{V}/stops/nearby"
        assert httpx.get(url, params=dict(lat=28.612345, lon=77.209876, radius_m=500)).status_code == 200
        assert httpx.get(url, params=dict(lat=19.0760, lon=72.8777)).status_code == 422           # error path must not echo either
        assert httpx.get(url, params=dict(lat="28.6123x", lon=77.209876)).status_code == 422      # validation-error path
    finally:
        proc.terminate()
        out = proc.communicate(timeout=15)[0]
    assert "/stops/nearby" in out and "[redacted]" in out                       # the request WAS logged, minus the coordinates
    for needle in ("28.612345", "77.209876", "19.0760", "72.8777", "28.6123x"):
        assert needle not in out, f"coordinate {needle!r} leaked into the server log"
