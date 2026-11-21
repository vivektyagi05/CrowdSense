"""Stop search, stop detail and scheduled departures."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from app.errors import AppError
from app.gtfs.calendar import get_active_service_ids
from app.schemas import Departure, DeparturesResponse, StopDetail, StopRoute, StopSearchResponse, StopWithCluster

DEPARTURES_NOTICE = ("Scheduled departures from static GTFS. These are not live predictions: real buses may run "
                     "early, late or not at all.")


def escape_like(term: str) -> str:
    """Make ``%``, ``_`` and ``\\`` in user input match literally in a LIKE pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def cluster_ids_for(conn: sqlite3.Connection, stop_ids: list[str]) -> dict[str, str]:
    """stop_id -> cluster_id (Phase 4 derived data). Empty when the derived tables have not been built."""
    if not stop_ids or conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'cluster_members'").fetchone() is None:
        return {}
    marks = ",".join("?" for _ in stop_ids)
    return dict(conn.execute(f"SELECT stop_id, cluster_id FROM cluster_members WHERE stop_id IN ({marks})", stop_ids).fetchall())


def search_stops(
    conn: sqlite3.Connection,
    query: str | None,
    limit: int,
    *,
    offset: int = 0,
    bbox: tuple[float, float, float, float] | None = None,
    route_id: str | None = None,
) -> StopSearchResponse:
    """List stops, optionally filtered by name substring, bounding box and/or serving route.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)``. Name matching is a case-insensitive substring
    search; the leading wildcard cannot use an index, but ~7k stops scan in a few milliseconds.
    """
    where: list[str] = []
    params: list[object] = []
    if query:
        where.append("lower(stop_name) LIKE lower(?) ESCAPE '\\'")
        params.append("%" + escape_like(query) + "%")
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        where.append("stop_lat BETWEEN ? AND ? AND stop_lon BETWEEN ? AND ?")
        params += [min_lat, max_lat, min_lon, max_lon]
    if route_id:
        if conn.execute("SELECT 1 FROM routes WHERE route_id = ?", (route_id,)).fetchone() is None:
            raise AppError(404, "route_not_found", f"Unknown route_id: {route_id!r}.")
        where.append("stop_id IN (SELECT st.stop_id FROM trips t JOIN stop_times st ON st.trip_id = t.trip_id "
                     "WHERE t.route_id = ?)")
        params.append(route_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM stops{clause}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops{clause} ORDER BY stop_name, stop_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    clusters = cluster_ids_for(conn, [r["stop_id"] for r in rows])
    return StopSearchResponse(items=[StopWithCluster(**dict(row), cluster_id=clusters.get(row["stop_id"])) for row in rows],
                              total=total, limit=limit, offset=offset)


def get_stop(conn: sqlite3.Connection, stop_id: str) -> StopDetail:
    row = conn.execute(
        "SELECT stop_id, stop_name, stop_lat, stop_lon, stop_code, stop_desc, zone_id, stop_url, location_type, "
        "parent_station, stop_timezone, wheelchair_boarding, platform_code FROM stops WHERE stop_id = ?", (stop_id,)
    ).fetchone()
    if row is None:
        raise AppError(404, "stop_not_found", f"Unknown stop_id: {stop_id!r}.")
    # One join answers "which routes serve this stop" (idx_stoptimes_stop -> trips PK -> routes PK).
    routes = conn.execute(
        "SELECT r.route_id, r.route_short_name, r.route_long_name, COUNT(*) AS stop_time_count "
        "FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id "
        "WHERE st.stop_id = ? GROUP BY r.route_id ORDER BY r.route_short_name, r.route_id", (stop_id,)
    ).fetchall()
    return StopDetail(**dict(row), cluster_id=cluster_ids_for(conn, [stop_id]).get(stop_id), stop_time_count=sum(r["stop_time_count"] for r in routes),
                      routes=[StopRoute(**dict(r)) for r in routes])


def _fmt_seconds(total: int) -> str:
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def get_departures(conn: sqlite3.Connection, stop_id: str, service_date: date, after_seconds: int, limit: int) -> DeparturesResponse:
    """Next scheduled departures from ``stop_id`` at or after ``after_seconds`` on ``service_date``.

    Correct across midnight: besides the services of ``service_date`` it also looks at the *previous*
    service day's trips whose GTFS times run past 24:00:00 (a 25:10:00 departure of yesterday is 01:10 today).
    """
    if conn.execute("SELECT 1 FROM stops WHERE stop_id = ?", (stop_id,)).fetchone() is None:
        raise AppError(404, "stop_not_found", f"Unknown stop_id: {stop_id!r}.")
    items: list[tuple[int, Departure]] = []
    # offset 0 = trips that started today, offset 1 = trips that started yesterday and run past midnight
    for day_offset in (0, 1):
        day = service_date - timedelta(days=day_offset)
        services = sorted(get_active_service_ids(conn, day))
        if not services:
            continue
        marks = ",".join("?" for _ in services)
        threshold = after_seconds + 86400 * day_offset
        rows = conn.execute(
            "SELECT st.trip_id, st.stop_sequence, st.departure_time, st.pickup_type, t.route_id, t.trip_headsign, "
            "r.route_short_name, r.route_long_name "
            "FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id "
            f"WHERE st.stop_id = ? AND st.departure_time >= ? AND t.service_id IN ({marks}) "
            "ORDER BY st.departure_time, st.trip_id LIMIT ?",
            (stop_id, _fmt_seconds(threshold), *services, limit),
        ).fetchall()
        for row in rows:
            h, m, s = (int(p) for p in row["departure_time"].split(":"))
            gtfs_seconds = h * 3600 + m * 60 + s
            base = datetime.combine(day, datetime.min.time())
            items.append((gtfs_seconds - 86400 * day_offset, Departure(
                trip_id=row["trip_id"], route_id=row["route_id"], route_short_name=row["route_short_name"],
                route_long_name=row["route_long_name"], trip_headsign=row["trip_headsign"],
                stop_sequence=row["stop_sequence"], departure_time=row["departure_time"],
                departure=(base + timedelta(seconds=gtfs_seconds)).isoformat(),
                service_date=day.isoformat(), pickup_type=row["pickup_type"])))
    items.sort(key=lambda pair: (pair[0], pair[1].trip_id))
    return DeparturesResponse(stop_id=stop_id, date=service_date.isoformat(), after=_fmt_seconds(after_seconds),
                              items=[d for _, d in items[:limit]], notice=DEPARTURES_NOTICE)
