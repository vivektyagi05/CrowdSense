"""Phase 4 / M3: Ramer-Douglas-Peucker and projection properties (Hypothesis, test-only dependency)."""
from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app.geo.planar import (Plane, PolylineIndex, distance_to_polyline, haversine_m, monotone_match, polyline_length,
                            rdp, slice_polyline)

SETTINGS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def road_like(draw, min_len_m=2000.0):
    """Polyline of 'road-like' geometry: steps 15-300 m, heading changes <= ~0.35 rad. Not arbitrary noise."""
    n = draw(st.integers(min_value=12, max_value=400))
    heading = draw(st.floats(0, 2 * math.pi))
    x = y = 0.0
    pts = [(x, y)]
    for _ in range(n):
        heading += draw(st.floats(-0.35, 0.35))
        step = draw(st.floats(15.0, 300.0))
        x += step * math.cos(heading); y += step * math.sin(heading)
        pts.append((x, y))
    if polyline_length(pts) < min_len_m:
        pts = [(px * 10, py * 10) for px, py in pts]
    return pts


@given(line=road_like(), tol=st.floats(1.0, 50.0))
@SETTINGS
def test_rdp_endpoints_order_and_max_deviation(line, tol):
    keep = rdp(line, tol)
    assert keep[0] == 0 and keep[-1] == len(line) - 1            # endpoints preserved
    assert keep == sorted(set(keep))                              # strictly increasing: a subsequence of the input
    simplified = [line[i] for i in keep]
    worst = max(distance_to_polyline(p, simplified) for p in line)
    assert worst <= tol + 1e-6                                    # max deviation <= tolerance


@given(line=road_like(), tol=st.floats(1.0, 5.0))
@SETTINGS
def test_rdp_never_lengthens_and_length_stays_within_one_percent_at_default_scale(line, tol):
    keep = rdp(line, tol)
    simplified = [line[i] for i in keep]
    a, b = polyline_length(line), polyline_length(simplified)
    assert b <= a + 1e-6                                          # triangle inequality: always true
    assert b >= a * 0.99                                          # within 1 % for road-like lines of >= 2 km at <= 5 m


@given(line=road_like(), tol=st.floats(1.0, 50.0))
@SETTINGS
def test_rdp_is_idempotent(line, tol):
    once = [line[i] for i in rdp(line, tol)]
    assert [once[i] for i in rdp(once, tol)] == once


@given(st.lists(st.tuples(st.floats(-1e4, 1e4), st.floats(-1e4, 1e4)), min_size=0, max_size=2))
def test_rdp_tiny_inputs(pts):
    assert rdp(pts, 5.0) == list(range(len(pts)))


def test_rdp_does_not_use_degrees():
    """Same shape at 28.6 N expressed in degrees: a 5 m tolerance must act on metres, not on 5 degrees."""
    plane = Plane(28.6, 77.2)
    lonlat = [(77.2 + i * 0.0001, 28.6 + (0.00003 if i == 5 else 0.0)) for i in range(11)]  # a ~3.3 m bump
    line = [plane.to_xy(*p) for p in lonlat]
    assert rdp(line, 5.0) == [0, 10]            # bump < 5 m: removed
    kept = rdp(line, 1.0)                       # bump (3.3 m) > 1 m: its apex is kept, and the 1 m bound still holds
    assert 5 in kept and kept[0] == 0 and kept[-1] == 10
    assert max(distance_to_polyline(p, [line[i] for i in kept]) for p in line) <= 1.0 + 1e-6


def test_plane_roundtrip_and_scale():
    plane = Plane(28.6, 77.2)
    x, y = plane.to_xy(77.21, 28.61)
    assert plane.to_lonlat(x, y) == pytest.approx((77.21, 28.61), abs=1e-9)
    assert math.hypot(x, y) == pytest.approx(haversine_m(28.6, 77.2, 28.61, 77.21), rel=0.001)


@given(line=road_like(), data=st.data())
@SETTINGS
def test_matching_a_stop_to_its_own_vertex_is_exact_and_monotone(line, data):
    idx = PolylineIndex(line, reach_m=60.0)
    ks = sorted(data.draw(st.lists(st.integers(0, len(line) - 1), min_size=2, max_size=8, unique=True)))
    m = monotone_match(idx, [line[k] for k in ks], 60.0)
    assert all(c is not None for c in m)
    along = [c.along_m for c in m]
    assert along == sorted(along)
    assert all(c.dist_m <= 60.0 for c in m)


@given(line=road_like(), data=st.data())
@SETTINGS
def test_slice_length_equals_along_difference(line, data):
    """Slicing between two projected points yields a polyline whose length is exactly the along-line difference."""
    idx = PolylineIndex(line, reach_m=60.0)
    i, j = sorted(data.draw(st.lists(st.integers(0, len(line) - 2), min_size=2, max_size=2, unique=True)))
    t1, t2 = data.draw(st.floats(0, 1)), data.draw(st.floats(0, 1))
    from app.geo.planar import Candidate
    a = Candidate(i, t1, idx.cum[i] + t1 * (idx.cum[i + 1] - idx.cum[i]), 0.0)
    b = Candidate(j, t2, idx.cum[j] + t2 * (idx.cum[j + 1] - idx.cum[j]), 0.0)
    s_ = slice_polyline(line, idx.cum, a, b)
    assert polyline_length(s_) == pytest.approx(b.along_m - a.along_m, abs=1e-3)
