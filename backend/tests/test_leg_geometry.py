"""Phase 4 / M3: leg geometry endpoint, on a SYNTHETIC road world with known geometry (see tests/geo_world.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gtfs.importer import import_gtfs
from app.main import create_app
from app.geo.planar import haversine_m
from tests.geo_world import LAT0, LON0, feed
from tests.gtfs_factory import build_zip

V = "/api/v1"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("geo")
    s = Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(d / "g.sqlite3"), "GTFS_ZIP": str(d / "f.zip")})
    import_gtfs(build_zip(d / "f.zip", base=feed()), s.database_path, promote_retries=0)
    return TestClient(create_app(s), raise_server_exceptions=False)


def leg(c, trip, a, b, **kw):
    return c.get(f"{V}/trips/{trip}/shape", params={"from_stop_id": a, "to_stop_id": b, **kw})


def test_normal_leg_is_a_slice_of_the_road_with_interpolated_ends(world):
    r = leg(world, "T_LINE", "S1", "S3")
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ok" and j["data_basis"] == "gtfs_shape" and j["shape_id"] == "SH_LINE"
    # every returned point lies on the road (lat 28.60) and between the stops' longitudes
    lons = [c[0] for c in j["coordinates"]]
    assert all(abs(c[1] - LAT0) < 1e-6 for c in j["coordinates"])
    assert lons[0] == pytest.approx(LON0 + 0.002, abs=1e-6) and lons[-1] == pytest.approx(LON0 + 0.006, abs=1e-6)
    expected = haversine_m(LAT0, LON0 + 0.002, LAT0, LON0 + 0.006)
    assert j["length_m"] == pytest.approx(expected, rel=0.005)
    assert j["boarding"]["stop_id"] == "S1" and 10 < j["boarding"]["distance_to_shape_m"] < 12   # stops sit ~11 m off the road
    assert j["point_count_original"] >= j["point_count_returned"] >= 2
    assert j["simplified"] is True            # a straight road collapses to its end points at 5 m


def test_collinear_points_collapse_but_a_real_bend_is_kept(world):
    j = leg(world, "T_LOOP", "L0", "L4").json()
    assert j["status"] == "ok" and j["match_method"] == "projection"
    corner = [c for c in j["coordinates"] if abs(c[0] - (LON0 + 0.010)) < 1e-5 and abs(c[1] - LAT0) < 1e-5]
    assert corner, "the rectangle's corner must survive simplification"


def test_loop_trip_picks_the_right_occurrence(world):
    first = leg(world, "T_LOOP", "L0", "L2").json()           # short way: first call of L0 -> L2
    full = leg(world, "T_LOOP", "L0", "L0").json()            # alight = first LATER call of L0 -> the whole loop
    assert first["status"] == full["status"] == "ok"
    assert first["length_m"] == pytest.approx(haversine_m(LAT0, LON0, LAT0, LON0 + 0.010), rel=0.01)
    perimeter = 2 * (haversine_m(LAT0, LON0, LAT0, LON0 + 0.010) + haversine_m(LAT0, LON0, LAT0 + 0.010, LON0))
    assert full["length_m"] == pytest.approx(perimeter, rel=0.02)
    # second occurrence of L0 as BOARDING is picked with board=<its departure time>: only the last call remains -> no later L0 -> 422
    last_dep = world.get(f"{V}/trips/T_LOOP/stop-times", params={"limit": 100}).json()["items"][-1]["departure_time"]
    r = leg(world, "T_LOOP", "L0", "L2", board=last_dep)
    assert r.status_code == 422 and r.json()["error"]["code"] == "alight_before_board"


def test_out_and_back_on_the_same_road_is_resolved_by_trip_order(world):
    out = leg(world, "T_BACK", "X0", "X1").json()             # first X0 -> first X1: the outbound half only
    back = leg(world, "T_BACK", "X2", "X0").json()            # X2 -> later X0: the return half only
    assert out["status"] == back["status"] == "ok"
    half = haversine_m(LAT0, LON0, LAT0, LON0 + 0.005)
    assert out["length_m"] == pytest.approx(half, rel=0.01) and back["length_m"] == pytest.approx(2 * half, rel=0.01)
    total = leg(world, "T_BACK", "X0", "X0").json()           # from the first X0 to the first LATER X0: out and back
    assert total["length_m"] == pytest.approx(4 * half, rel=0.01)


def test_no_shape_is_a_structured_200_never_a_guess(world):
    r = leg(world, "T_NOSHAPE", "S0", "S1")
    j = r.json()
    assert r.status_code == 200 and j["status"] == "no_shape" and j["coordinates"] == [] and j["reason"] == "trip_has_no_shape_id"
    assert j["boarding"] is None and j["data_basis"] == "gtfs_shape"


def test_projection_failure_reports_measured_distance_and_returns_no_line(world):
    j = leg(world, "T_FAR", "S0", "FAR").json()
    assert j["status"] == "unreliable_projection" and j["coordinates"] == []
    assert j["reason"].startswith("alighting_stop_farther_than_60m")
    assert 400 < j["alighting"]["distance_to_shape_m"] < 700 and j["boarding"]["distance_to_shape_m"] < 20
    # an unmatched INTERMEDIATE stop does not spoil a leg whose end points match
    assert leg(world, "T_FAR", "S0", "S5").json()["status"] == "ok"


def test_shape_dist_traveled_used_only_when_valid_and_consistent(world):
    assert leg(world, "T_DIST_OK", "S1", "S3").json()["match_method"] == "shape_dist_traveled"
    j = leg(world, "T_DIST_UNIT", "S1", "S3").json()                                          # wrong unit -> inconsistent -> ignored
    assert j["match_method"] == "projection" and j["status"] == "ok"
    assert leg(world, "T_LINE", "S1", "S3").json()["match_method"] == "projection"           # absent -> projection


def test_both_methods_agree_on_the_same_leg(world):
    a, b = leg(world, "T_DIST_OK", "S1", "S4").json(), leg(world, "T_LINE", "S1", "S4").json()
    assert a["length_m"] == pytest.approx(b["length_m"], rel=0.01)


@pytest.mark.parametrize("params,status,code", [
    (dict(from_stop_id="NOPE", to_stop_id="S1"), 404, "stop_not_on_trip"),
    (dict(from_stop_id="S1", to_stop_id="NOPE"), 404, "stop_not_on_trip"),
    (dict(from_stop_id="S3", to_stop_id="S1"), 422, "alight_before_board"),
    (dict(from_stop_id="S1"), 422, "validation_error"),
    (dict(to_stop_id="S1"), 422, "validation_error"),
    (dict(from_stop_id="S1", to_stop_id="S2", board="25pm"), 422, "validation_error"),
])
def test_validation_and_stop_not_on_trip(world, params, status, code):
    r = world.get(f"{V}/trips/T_LINE/shape", params=params)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_unknown_trip_is_404(world):
    assert leg(world, "NOPE", "S1", "S2").status_code == 404


def test_tolerance_is_clamped_and_reported(world):
    assert leg(world, "T_LINE", "S0", "S5", tolerance_m=1000).json()["tolerance_m"] == 50.0
    assert leg(world, "T_LINE", "S0", "S5", tolerance_m=0.1).json()["tolerance_m"] == 1.0
    assert leg(world, "T_LINE", "S0", "S5").json()["tolerance_m"] == 5.0
    assert world.get(f"{V}/trips/T_LINE/shape", params=dict(from_stop_id="S0", to_stop_id="S1", tolerance_m="nan")).status_code == 422


def test_board_time_forms_are_accepted(world):
    assert leg(world, "T_LINE", "S0", "S1", board="08:00").status_code == 200
    assert leg(world, "T_LINE", "S0", "S1", board="8:00:00").status_code == 200


def test_legacy_shape_endpoint_is_unchanged(world):
    j = world.get(f"{V}/trips/T_LINE/shape").json()
    assert j["shape_available"] is True and j["geometry_source"] == "gtfs_shape" and "status" not in j and len(j["points"]) == 11


def test_route_shapes_default_is_unchanged_and_geometry_is_opt_in(world):
    plain = world.get(f"{V}/routes/RLINE/shapes").json()
    assert plain["items"] == [{"shape_id": "SH_LINE", "trip_count": 1, "point_count": 11}]
    g = world.get(f"{V}/routes/RLINE/shapes", params={"geometry": "true"}).json()["items"][0]
    assert g["geometry_status"] == "ok" and g["data_basis"] == "gtfs_shape" and g["point_count_original"] == 11
    assert g["coordinates"][0][0] == pytest.approx(LON0) and g["coordinates"][-1][0] == pytest.approx(LON0 + 0.010)


def test_route_shapes_hard_cap_raises_tolerance_not_the_cap(world):
    g = world.get(f"{V}/routes/RLOOP/shapes", params={"geometry": "true", "tolerance_m": 1, "max_points": 10}).json()["items"][0]
    assert g["point_count_returned"] <= 10 and g["tolerance_m"] >= 1
    assert world.get(f"{V}/routes/RLINE/shapes", params={"geometry": "true", "max_points": 5}).status_code == 422


def test_route_without_shape_says_so(world):
    g = world.get(f"{V}/routes/RNOSH/shapes", params={"geometry": "true"}).json()["items"][0]
    assert g["geometry_status"] == "no_shape" and g["coordinates"] == []


def test_non_monotone_distances_are_ignored_at_unit_level():
    """The importer already rejects decreasing shape_dist_traveled, so this branch is exercised directly."""
    from app.geo.planar import PolylineIndex
    from app.services.leg_service import _candidates_from_dist
    line = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (300.0, 0.0)]
    idx = PolylineIndex(line, reach_m=60)
    calls = [{"dist": 0.0}, {"dist": 150.0}, {"dist": 300.0}]
    xy = [(0.0, 5.0), (150.0, 5.0), (300.0, 5.0)]
    ok = _candidates_from_dist(idx, [0.0, 100.0, 200.0, 300.0], calls, xy, 60)
    assert ok is not None and [round(c.along_m) for c in ok] == [0, 150, 300]
    assert _candidates_from_dist(idx, [0.0, 100.0, 50.0, 300.0], calls, xy, 60) is None            # shape dist decreases
    assert _candidates_from_dist(idx, [0.0, 100.0, 200.0, 300.0], [{"dist": 0.0}, {"dist": 200.0}, {"dist": 100.0}], xy, 60) is None  # stop dist decreases
    assert _candidates_from_dist(idx, [0.0, 100.0, 200.0, 300.0], [{"dist": 0.0}, {"dist": None}, {"dist": 300.0}], xy, 60) is None  # missing
    assert _candidates_from_dist(idx, [None, None, None, None], calls, xy, 60) is None
    assert _candidates_from_dist(idx, [0.0, 100.0, 200.0, 300.0], calls, [(0.0, 5.0), (150.0, 500.0), (300.0, 5.0)], 60) is None  # inconsistent with geometry
