"""Agencies, routes, trips and stop-times: read-only queries over the imported GTFS network.

All list queries are bounded by ``limit`` and run as single SQL statements (joins / sub-selects), never
one query per row.
"""

from __future__ import annotations

import sqlite3

from app.errors import AppError
from app.schemas import (
    AgencyList, AgencyOut, RouteDetail, RouteItem, RouteList, RouteShapeRef, StopEnd, StopTimeItem, StopTimeList,
    TripDetail, TripItem, TripList,
)
from app.services.stops_service import escape_like


def list_agencies(conn: sqlite3.Connection) -> AgencyList:
    rows = conn.execute("SELECT * FROM agency ORDER BY agency_name, agency_id").fetchall()
    return AgencyList(items=[AgencyOut(**dict(r)) for r in rows], total=len(rows))


_ROUTE_COLUMNS = "route_id, agency_id, route_short_name, route_long_name, route_desc, route_type, route_color"


def list_routes(conn: sqlite3.Connection, q: str | None, agency_id: str | None, route_type: int | None,
                limit: int, offset: int) -> RouteList:
    where: list[str] = []
    params: list[object] = []
    if q:
        where.append("(lower(route_short_name) LIKE lower(?) ESCAPE '\\' OR lower(route_long_name) LIKE lower(?) ESCAPE '\\')")
        pattern = "%" + escape_like(q) + "%"
        params += [pattern, pattern]
    if agency_id is not None:
        where.append("agency_id = ?")
        params.append(agency_id)
    if route_type is not None:
        where.append("route_type = ?")
        params.append(route_type)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM routes{clause}", params).fetchone()[0]
    rows = conn.execute(f"SELECT {_ROUTE_COLUMNS} FROM routes{clause} ORDER BY route_short_name, route_id LIMIT ? OFFSET ?",
                        [*params, limit, offset]).fetchall()
    return RouteList(items=[RouteItem(**dict(r)) for r in rows], total=total, limit=limit, offset=offset)


def _require_route(conn: sqlite3.Connection, route_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM routes WHERE route_id = ?", (route_id,)).fetchone()
    if row is None:
        raise AppError(404, "route_not_found", f"Unknown route_id: {route_id!r}.")
    return row


def route_shapes(conn: sqlite3.Connection, route_id: str) -> list[RouteShapeRef]:
    rows = conn.execute(
        "SELECT t.shape_id, COUNT(*) AS trip_count, s.point_count FROM trips t "
        "LEFT JOIN shapes s ON s.shape_id = t.shape_id WHERE t.route_id = ? "
        "GROUP BY t.shape_id ORDER BY trip_count DESC, t.shape_id", (route_id,)).fetchall()
    return [RouteShapeRef(**dict(r)) for r in rows]


def get_route(conn: sqlite3.Connection, route_id: str) -> RouteDetail:
    row = _require_route(conn, route_id)
    agency = None
    agency_row = conn.execute("SELECT * FROM agency WHERE agency_id = ?", (row["agency_id"] or "",)).fetchone() \
        if row["agency_id"] is not None else (
            conn.execute("SELECT * FROM agency").fetchone() if conn.execute("SELECT COUNT(*) FROM agency").fetchone()[0] == 1 else None)
    if agency_row is not None:
        agency = AgencyOut(**dict(agency_row))
    trips = conn.execute("SELECT service_id, direction_id, COUNT(*) AS n FROM trips WHERE route_id = ? "
                         "GROUP BY service_id, direction_id", (route_id,)).fetchall()
    directions: dict[str, int] = {}
    for t in trips:
        key = "unspecified" if t["direction_id"] is None else str(t["direction_id"])
        directions[key] = directions.get(key, 0) + t["n"]
    stop_count = conn.execute(
        "SELECT COUNT(DISTINCT st.stop_id) FROM trips t JOIN stop_times st ON st.trip_id = t.trip_id WHERE t.route_id = ?",
        (route_id,)).fetchone()[0]
    return RouteDetail(
        **{k: row[k] for k in (*_ROUTE_COLUMNS.split(", "), "route_url", "route_text_color", "route_sort_order")},
        agency=agency, trip_count=sum(directions.values()), stop_count=stop_count,
        service_ids=sorted({t["service_id"] for t in trips}), directions=directions, shapes=route_shapes(conn, route_id))


def list_route_trips(conn: sqlite3.Connection, route_id: str, service_id: str | None, limit: int, offset: int) -> TripList:
    _require_route(conn, route_id)
    where, params = "t.route_id = ?", [route_id]
    if service_id is not None:
        where += " AND t.service_id = ?"
        params.append(service_id)
    total = conn.execute(f"SELECT COUNT(*) FROM trips t WHERE {where}", params).fetchone()[0]
    # first_departure is a correlated sub-select over the UNIQUE (trip_id, stop_sequence) index: it only runs for
    # the trips of ONE route (hundreds at most), not for the 2.4M-row table.
    rows = conn.execute(
        "SELECT t.trip_id, t.route_id, t.service_id, t.trip_headsign, t.direction_id, t.shape_id, "
        "(SELECT s.departure_time FROM stop_times s WHERE s.trip_id = t.trip_id ORDER BY s.stop_sequence LIMIT 1) "
        f"AS first_departure FROM trips t WHERE {where} ORDER BY first_departure, t.trip_id LIMIT ? OFFSET ?",
        [*params, limit, offset]).fetchall()
    return TripList(items=[TripItem(**dict(r)) for r in rows], total=total, limit=limit, offset=offset)


def _stop_end(conn: sqlite3.Connection, trip_id: str, order: str) -> StopEnd | None:
    row = conn.execute(
        "SELECT st.stop_id, p.stop_name, st.stop_sequence, COALESCE(st.departure_time, st.arrival_time) AS time_ "
        "FROM stop_times st JOIN stops p ON p.stop_id = st.stop_id WHERE st.trip_id = ? "
        f"ORDER BY st.stop_sequence {order} LIMIT 1", (trip_id,)).fetchone()
    if row is None:
        return None
    return StopEnd(stop_id=row["stop_id"], stop_name=row["stop_name"], stop_sequence=row["stop_sequence"], time=row["time_"])


def require_trip(conn: sqlite3.Connection, trip_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT t.*, r.route_short_name, r.route_long_name FROM trips t JOIN routes r ON r.route_id = t.route_id "
        "WHERE t.trip_id = ?", (trip_id,)).fetchone()
    if row is None:
        raise AppError(404, "trip_not_found", f"Unknown trip_id: {trip_id!r}.")
    return row


def get_trip(conn: sqlite3.Connection, trip_id: str) -> TripDetail:
    row = require_trip(conn, trip_id)
    stop_count = conn.execute("SELECT COUNT(*) FROM stop_times WHERE trip_id = ?", (trip_id,)).fetchone()[0]
    data = {k: row[k] for k in ("trip_id", "route_id", "route_short_name", "route_long_name", "service_id",
                                "trip_headsign", "trip_short_name", "direction_id", "block_id", "shape_id",
                                "wheelchair_accessible", "bikes_allowed")}
    return TripDetail(**data, has_shape=row["shape_id"] is not None, stop_count=stop_count,
                      first_stop=_stop_end(conn, trip_id, "ASC"), last_stop=_stop_end(conn, trip_id, "DESC"))


def list_trip_stop_times(conn: sqlite3.Connection, trip_id: str, limit: int, offset: int) -> StopTimeList:
    require_trip(conn, trip_id)
    total = conn.execute("SELECT COUNT(*) FROM stop_times WHERE trip_id = ?", (trip_id,)).fetchone()[0]
    rows = conn.execute(
        "SELECT st.stop_sequence, st.stop_id, p.stop_name, p.stop_lat, p.stop_lon, st.arrival_time, st.departure_time, "
        "st.pickup_type, st.drop_off_type, st.timepoint, st.shape_dist_traveled, st.fare_stage "
        "FROM stop_times st JOIN stops p ON p.stop_id = st.stop_id WHERE st.trip_id = ? "
        "ORDER BY st.stop_sequence LIMIT ? OFFSET ?", (trip_id, limit, offset)).fetchall()
    return StopTimeList(trip_id=trip_id, items=[StopTimeItem(**dict(r)) for r in rows], total=total, limit=limit, offset=offset)
