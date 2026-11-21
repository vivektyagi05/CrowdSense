"""Leg geometry: the part of a trip's GTFS shape between a boarding and an alighting stop.

Never invents a path. Every non-``ok`` outcome is explicit and structured (``no_shape`` /
``unreliable_projection``), and the response says which method placed the stops on the line.
"""
from __future__ import annotations

import bisect
import re
import sqlite3
from typing import Any

from app.errors import AppError
from app.geo.planar import (Candidate, Plane, PolylineIndex, haversine_m, monotone_match, polyline_length, rdp,
                            slice_polyline, _point_segment)
from app.services.network_service import require_trip

MATCH_THRESHOLD_M = 60.0          # documented default; see docs/phase4/DECISIONS.md ADR-04
DEFAULT_TOLERANCE_M = 5.0
MIN_TOLERANCE_M, MAX_TOLERANCE_M = 1.0, 50.0
_TIME = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")


def clamp_tolerance(value: float | None) -> float:
    if value is None:
        return DEFAULT_TOLERANCE_M
    return max(MIN_TOLERANCE_M, min(MAX_TOLERANCE_M, float(value)))


def normalise_board(raw: str | None) -> str | None:
    """'HH:MM' or 'HH:MM:SS' (hours may exceed 23) -> zero-padded 'HH:MM:SS'; anything else is a validation error."""
    if raw is None:
        return None
    text = raw.strip()
    if re.fullmatch(r"\d{1,2}:[0-5]\d", text):
        text += ":00"
    m = _TIME.match(text)
    if not m:
        raise AppError(422, "validation_error", "board must be HH:MM or HH:MM:SS.")
    return f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3)}"


def _load_shape(conn: sqlite3.Connection, shape_id: str) -> list[tuple[float, float, float | None]]:
    rows = conn.execute("SELECT shape_pt_lon, shape_pt_lat, shape_dist_traveled FROM shape_points "
                        "WHERE shape_id = ? ORDER BY shape_pt_sequence", (shape_id,)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _load_calls(conn: sqlite3.Connection, trip_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT st.stop_sequence, st.stop_id, st.departure_time, st.arrival_time, st.shape_dist_traveled AS dist, "
        "s.stop_lat, s.stop_lon FROM stop_times st JOIN stops s ON s.stop_id = st.stop_id "
        "WHERE st.trip_id = ? ORDER BY st.stop_sequence", (trip_id,)).fetchall()


def resolve_calls(calls: list[sqlite3.Row], from_stop_id: str, to_stop_id: str, board: str | None) -> tuple[int, int]:
    """Indices (into ``calls``) of the boarding and alighting calls. Loop-safe."""
    boards = [i for i, c in enumerate(calls) if c["stop_id"] == from_stop_id]
    if not boards:
        raise AppError(404, "stop_not_on_trip", f"Stop {from_stop_id!r} is not served by this trip.")
    bi = boards[0]
    if board is not None:
        for i in boards:
            dep = calls[i]["departure_time"] or calls[i]["arrival_time"]
            if dep is not None and _pad(dep) == board:
                bi = i
                break
    ai = next((i for i in range(bi + 1, len(calls)) if calls[i]["stop_id"] == to_stop_id), None)
    if ai is None:
        if not any(c["stop_id"] == to_stop_id for c in calls):
            raise AppError(404, "stop_not_on_trip", f"Stop {to_stop_id!r} is not served by this trip.")
        raise AppError(422, "alight_before_board", f"Stop {to_stop_id!r} is not served after boarding at {from_stop_id!r}.")
    return bi, ai


def _pad(t: str) -> str:
    h, m, s = t.split(":")
    return f"{int(h):02d}:{m}:{s}"


def _candidates_from_dist(index: PolylineIndex, shape_dist: list[float | None], calls: list[sqlite3.Row],
                          stop_xy: list[tuple[float, float]], threshold_m: float) -> list[Candidate] | None:
    """Positions from shape_dist_traveled, or None when the data is absent, non-monotone or inconsistent with geometry."""
    stop_d = [c["dist"] for c in calls]
    if any(d is None for d in stop_d) or any(d is None for d in shape_dist):
        return None
    if any(b < a for a, b in zip(stop_d, stop_d[1:])) or any(b < a for a, b in zip(shape_dist, shape_dist[1:])):
        return None
    sd = [float(d) for d in shape_dist]
    out: list[Candidate] = []
    for d, p in zip(stop_d, stop_xy):
        if d < sd[0] or d > sd[-1] or sd[-1] == sd[0]:
            return None
        k = min(max(bisect.bisect_right(sd, d) - 1, 0), len(sd) - 2)
        span = sd[k + 1] - sd[k]
        t = 0.0 if span == 0 else (d - sd[k]) / span
        a, b = index.line[k], index.line[k + 1]
        q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        dist = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
        if dist > threshold_m:  # unit mismatch or wrong shape: do not trust shape_dist_traveled
            return None
        out.append(Candidate(k, t, index.cum[k] + t * (index.cum[k + 1] - index.cum[k]), dist))
    return out


def get_leg_shape(conn: sqlite3.Connection, trip_id: str, from_stop_id: str, to_stop_id: str, *, board: str | None,
                  tolerance_m: float | None, threshold_m: float = MATCH_THRESHOLD_M) -> dict[str, Any]:
    trip = require_trip(conn, trip_id)
    tol = clamp_tolerance(tolerance_m)
    base: dict[str, Any] = {"trip_id": trip_id, "shape_id": trip["shape_id"], "tolerance_m": tol,
                            "data_basis": "gtfs_shape", "coordinates": []}
    calls = _load_calls(conn, trip_id)
    bi, ai = resolve_calls(calls, from_stop_id, to_stop_id, normalise_board(board))
    shape_id = trip["shape_id"]
    pts = _load_shape(conn, shape_id) if shape_id else []
    if len(pts) < 2:
        return {**base, "status": "no_shape", "reason": "trip_has_no_shape_id" if shape_id is None else
                "shape_missing_or_too_short"}
    plane = Plane.around([(p[0], p[1]) for p in pts])
    line = [plane.to_xy(p[0], p[1]) for p in pts]
    index = PolylineIndex(line, reach_m=threshold_m)
    stop_xy = [plane.to_xy(c["stop_lon"], c["stop_lat"]) for c in calls]

    method = "projection"
    cands: list[Candidate | None] | None = _candidates_from_dist(index, [p[2] for p in pts], calls, stop_xy, threshold_m)
    if cands is not None:
        method = "shape_dist_traveled"
    else:
        cands = monotone_match(index, stop_xy, threshold_m)
    board_c, alight_c = cands[bi], cands[ai]

    def measured(i: int) -> float | None:
        """Distance to the nearest shape point of the whole line (diagnostic only, never used to draw)."""
        c = cands[i]
        if c is not None:
            return round(c.dist_m, 1)
        p = stop_xy[i]
        return round(min(_point_segment(p[0], p[1], *line[k], *line[k + 1])[0] for k in range(len(line) - 1)), 1)

    def unreliable(reason: str) -> dict[str, Any]:
        return {**base, "status": "unreliable_projection", "reason": reason, "match_method": method,
                "match_threshold_m": threshold_m,
                "boarding": {"stop_id": from_stop_id, "distance_to_shape_m": measured(bi)},
                "alighting": {"stop_id": to_stop_id, "distance_to_shape_m": measured(ai)}}

    if board_c is None or alight_c is None:
        side = "boarding" if board_c is None else "alighting"
        return unreliable(f"{side}_stop_farther_than_{threshold_m:g}m_from_shape")
    if alight_c.along_m < board_c.along_m - 1.0:
        return unreliable("alighting_projects_before_boarding")
    if alight_c.along_m - board_c.along_m < 1.0 and from_stop_id != to_stop_id:
        return unreliable("zero_length_leg")

    sliced = slice_polyline(line, index.cum, board_c, alight_c)
    keep = rdp(sliced, tol)
    simplified = [sliced[i] for i in keep]
    lonlat_full = [plane.to_lonlat(*p) for p in sliced]
    lonlat = [plane.to_lonlat(*p) for p in simplified]
    coords = [[round(lo, 6), round(la, 6)] for lo, la in lonlat]
    length = sum(haversine_m(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]) for i in range(len(coords) - 1))
    length_orig = sum(haversine_m(lonlat_full[i][1], lonlat_full[i][0], lonlat_full[i + 1][1], lonlat_full[i + 1][0])
                      for i in range(len(lonlat_full) - 1))
    return {**base, "status": "ok", "reason": None, "coordinates": coords, "point_count_original": len(sliced),
            "point_count_returned": len(coords), "simplified": len(coords) < len(sliced),
            "length_m": round(length, 1), "length_original_m": round(length_orig, 1),
            "match_method": method, "match_threshold_m": threshold_m,
            "boarding": {"stop_id": from_stop_id, "distance_to_shape_m": round(board_c.dist_m, 1)},
            "alighting": {"stop_id": to_stop_id, "distance_to_shape_m": round(alight_c.dist_m, 1)}}


def route_shapes_geometry(conn: sqlite3.Connection, route_id: str, items: list[dict[str, Any]], tolerance_m: float | None,
                          max_points: int) -> list[dict[str, Any]]:
    """Add simplified GeoJSON-order ``coordinates`` to route shape refs, capped at ``max_points`` per shape.

    If the line at the requested tolerance still exceeds the cap, the tolerance is doubled until it fits and the
    tolerance actually used is reported; the cap is a hard limit.
    """
    out = []
    for item in items:
        pts = _load_shape(conn, item["shape_id"]) if item.get("shape_id") else []
        if len(pts) < 2:
            out.append({**item, "geometry_status": "no_shape", "coordinates": []})
            continue
        plane = Plane.around([(p[0], p[1]) for p in pts])
        xy = [plane.to_xy(p[0], p[1]) for p in pts]
        tol = clamp_tolerance(tolerance_m)
        keep = rdp(xy, tol)
        while len(keep) > max_points:
            tol *= 2
            keep = rdp(xy, tol)
        coords = [[round(pts[i][0], 6), round(pts[i][1], 6)] for i in keep]  # original vertices: no resampling
        out.append({**item, "geometry_status": "ok", "coordinates": coords, "point_count_original": len(pts),
                    "point_count_returned": len(coords), "simplified": len(coords) < len(pts), "tolerance_m": tol,
                    "data_basis": "gtfs_shape"})
    return out
