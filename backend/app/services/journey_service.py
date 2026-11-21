"""Direct (single-bus) journey search over static GTFS.

Scope is unchanged from the original implementation: direct trips only, scheduled
times only, no transfers, no live data and **no crowd values** - every result
carries ``crowd.status == "NOT_AVAILABLE"``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.errors import AppError
from app.gtfs.calendar import get_active_service_ids
from app.gtfs_time import duration_minutes, gtfs_time_to_datetime
from app.schemas import CrowdInfo, JourneyItem, JourneySearchResponse

DATA_BASIS = "static GTFS scheduled service"
NOTICE = "Scheduled times only; no live ETA. Crowd estimation awaits official ETM/e-ticketing data."


def parse_departure(value: str) -> datetime:
    """Parse a *local* ISO datetime (no UTC offset), truncated to whole seconds."""
    try:
        requested = datetime.fromisoformat(value.strip())
    except ValueError:
        raise AppError(400, "invalid_departure", "Use ISO local datetime, e.g. 2026-11-09T08:00:00") from None
    if requested.tzinfo is not None:
        raise AppError(400, "invalid_departure",
                       "Use ISO local datetime without a UTC offset, e.g. 2026-11-09T08:00:00")
    return requested.replace(microsecond=0)


def active_services(conn: sqlite3.Connection, service_date: str) -> set[str]:
    """Service ids running on ``service_date`` (``YYYY-MM-DD``); see :mod:`app.gtfs.calendar`."""
    return get_active_service_ids(conn, datetime.strptime(service_date, "%Y-%m-%d").date())


def _require_stops(conn: sqlite3.Connection, origin: str, destination: str) -> None:
    found = {r["stop_id"] for r in conn.execute("SELECT stop_id FROM stops WHERE stop_id IN (?, ?)", (origin, destination))}
    for param, stop_id in (("origin_stop_id", origin), ("destination_stop_id", destination)):
        if stop_id not in found:
            raise AppError(404, "stop_not_found", f"Unknown {param}: {stop_id!r}. Select a stop from /api/v1/stops.")


def find_direct_journeys(
    conn: sqlite3.Connection, origin_stop_id: str, destination_stop_id: str, departure: str, limit: int
) -> JourneySearchResponse:
    requested = parse_departure(departure)
    origin, destination = origin_stop_id.strip(), destination_stop_id.strip()
    if origin == destination:
        raise AppError(400, "same_stop", "origin_stop_id and destination_stop_id must be different stops.")
    _require_stops(conn, origin, destination)

    service_date = requested.strftime("%Y-%m-%d")
    active = active_services(conn, service_date)
    if not active:
        return JourneySearchResponse(items=[], message="No active GTFS service for this date.")

    marks = ",".join("?" for _ in active)
    # The time filter lives in SQL so LIMIT applies to departures *at or after* the requested
    # time. (The original applied LIMIT 1000 first and filtered in Python, silently returning
    # nothing for late-day searches on busy stop pairs.) Importer-normalised HH:MM:SS strings
    # sort chronologically, including service-day hours >= 24.
    sql = (
        "SELECT t.trip_id, r.route_id, r.route_short_name, r.route_long_name, "
        "a.departure_time AS dep_time, b.arrival_time AS arr_time, "
        "a.stop_sequence AS from_seq, b.stop_sequence AS to_seq, "
        "os.stop_name AS origin_name, ds.stop_name AS destination_name "
        "FROM stop_times a "
        "JOIN stop_times b ON b.trip_id = a.trip_id AND b.stop_sequence > a.stop_sequence "
        "JOIN trips t ON t.trip_id = a.trip_id "
        "JOIN routes r ON r.route_id = t.route_id "
        "JOIN stops os ON os.stop_id = a.stop_id "
        "JOIN stops ds ON ds.stop_id = b.stop_id "
        f"WHERE a.stop_id = ? AND b.stop_id = ? AND t.service_id IN ({marks}) "
        "AND a.departure_time IS NOT NULL AND b.arrival_time IS NOT NULL "
        "AND a.departure_time >= ? AND b.arrival_time >= a.departure_time "
        "ORDER BY a.departure_time, a.trip_id LIMIT ?"
    )
    rows = conn.execute(
        sql, (origin, destination, *sorted(active), requested.strftime("%H:%M:%S"), limit)
    ).fetchall()

    items = []
    for row in rows:
        dep = gtfs_time_to_datetime(service_date, row["dep_time"])
        arr = gtfs_time_to_datetime(service_date, row["arr_time"])
        items.append(JourneyItem(
            trip_id=row["trip_id"],
            route_id=row["route_id"],
            route_name=row["route_short_name"] or row["route_long_name"] or row["route_id"],
            origin=row["origin_name"],
            destination=row["destination_name"],
            departure=dep.isoformat(),
            arrival=arr.isoformat(),
            scheduled_duration_minutes=duration_minutes(dep, arr),
            intermediate_stops=max(0, row["to_seq"] - row["from_seq"] - 1),
            crowd=CrowdInfo(),
            data_basis=DATA_BASIS,
        ))
    return JourneySearchResponse(items=items, mode="direct_only", notice=NOTICE)
