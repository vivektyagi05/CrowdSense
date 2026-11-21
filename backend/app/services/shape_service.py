"""Route geometry from the feed's own ``shapes.txt``.

A line is **never** drawn between stops when a shape exists. When a trip has no usable shape the response says so
explicitly (``shape_available=false`` + ``reason``). A clearly labelled fallback - the ordered stop coordinates of
the trip - is available on request (``fallback=stops``); it is a sequence of stops, not the road the bus drives.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.errors import AppError
from app.schemas import RouteShapes, ShapePoint, ShapeResponse
from app.services.network_service import require_trip, route_shapes, _require_route

FALLBACK_NOTE = ("No GTFS shape exists for this trip. These points are the trip's stops in stop_sequence order; "
                 "connecting them draws straight segments, NOT the road geometry. Label it as approximate on maps.")
DIST_NOTE = "shape_dist_traveled is in the feed's own, unspecified distance unit."


def _geojson(shape_id: str | None, trip_id: str | None, points: list[ShapePoint], source: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"shape_id": shape_id, "trip_id": trip_id, "geometry_source": source},
        "geometry": {"type": "LineString", "coordinates": [[p.lon, p.lat] for p in points]},
    }


def get_shape(conn: sqlite3.Connection, shape_id: str, *, trip_id: str | None = None, fmt: str = "points",
              limit: int = 5000, offset: int = 0) -> ShapeResponse:
    meta = conn.execute("SELECT * FROM shapes WHERE shape_id = ?", (shape_id,)).fetchone()
    if meta is None:
        raise AppError(404, "shape_not_found", f"Unknown shape_id: {shape_id!r}.")
    rows = conn.execute(
        "SELECT shape_pt_lat, shape_pt_lon, shape_pt_sequence, shape_dist_traveled FROM shape_points "
        "WHERE shape_id = ? ORDER BY shape_pt_sequence LIMIT ? OFFSET ?", (shape_id, limit, offset)).fetchall()
    points = [ShapePoint(lat=r[0], lon=r[1], sequence=r[2], dist_traveled=r[3]) for r in rows]
    response = ShapeResponse(
        trip_id=trip_id, shape_id=shape_id, shape_available=True, geometry_source="gtfs_shape", point_count=meta["point_count"],
        offset=offset, returned_points=len(points), bbox=[meta["min_lon"], meta["min_lat"], meta["max_lon"], meta["max_lat"]],
        max_dist_traveled=meta["max_dist_traveled"], note=DIST_NOTE)
    if fmt == "geojson":
        response.geojson = _geojson(shape_id, trip_id, points, "gtfs_shape")
    else:
        response.points = points
    return response


def _fallback(conn: sqlite3.Connection, trip_id: str, fmt: str, reason: str, shape_id: str | None) -> ShapeResponse:
    rows = conn.execute(
        "SELECT p.stop_lat, p.stop_lon, st.stop_sequence FROM stop_times st JOIN stops p ON p.stop_id = st.stop_id "
        "WHERE st.trip_id = ? AND p.stop_lat IS NOT NULL ORDER BY st.stop_sequence", (trip_id,)).fetchall()
    points = [ShapePoint(lat=r[0], lon=r[1], sequence=r[2]) for r in rows]
    bbox = ([min(p.lon for p in points), min(p.lat for p in points), max(p.lon for p in points), max(p.lat for p in points)]
            if points else None)
    response = ShapeResponse(trip_id=trip_id, shape_id=shape_id, shape_available=False, geometry_source="stop_sequence_fallback",
                             reason=reason, note=FALLBACK_NOTE, point_count=len(points), returned_points=len(points), bbox=bbox)
    if fmt == "geojson":
        response.geojson = _geojson(shape_id, trip_id, points, "stop_sequence_fallback")
    else:
        response.points = points
    return response


def get_trip_shape(conn: sqlite3.Connection, trip_id: str, *, fmt: str, fallback: str | None, limit: int, offset: int) -> ShapeResponse:
    trip = require_trip(conn, trip_id)
    shape_id = trip["shape_id"]
    reason = None
    if shape_id is None:
        reason = "trip_has_no_shape_id"
    elif conn.execute("SELECT 1 FROM shapes WHERE shape_id = ?", (shape_id,)).fetchone() is None:
        reason = "shape_id_not_in_shapes_txt"
    if reason is None:
        return get_shape(conn, shape_id, trip_id=trip_id, fmt=fmt, limit=limit, offset=offset)
    if fallback == "stops":
        return _fallback(conn, trip_id, fmt, reason, shape_id)
    return ShapeResponse(trip_id=trip_id, shape_id=shape_id, shape_available=False, geometry_source="none", reason=reason,
                         note="No shape data for this trip. Pass fallback=stops for the labelled stop-sequence polyline.",
                         point_count=0, returned_points=0)


def get_route_shapes(conn: sqlite3.Connection, route_id: str) -> RouteShapes:
    _require_route(conn, route_id)
    return RouteShapes(route_id=route_id, items=route_shapes(conn, route_id))
