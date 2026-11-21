"""Service-date evaluation: which GTFS ``service_id`` values run on a given local date.

GTFS semantics implemented (https://gtfs.org/documentation/schedule/reference/#calendartxt):

1. ``calendar.txt``: a service runs on ``date`` when the weekday flag of ``date`` is 1 and
   ``start_date <= date <= end_date`` (both inclusive).
2. ``calendar_dates.txt`` then overrides, for that exact date only:
   ``exception_type = 1`` -> the service runs (even outside its calendar range or on a disabled weekday),
   ``exception_type = 2`` -> the service does not run.
3. ``calendar.txt`` may be absent: services are then defined by ``exception_type = 1`` rows alone.
4. A ``service_id`` that appears only in ``trips.txt`` (no calendar row, no exception) never runs.

Nothing here assumes ``calendar_dates.txt`` exists, and nothing assumes a trip runs every day.

Service day vs. clock day: GTFS times past 24:00:00 belong to the service day on which the trip
*started*. Evaluating "what is running at 01:30 on the 11th" therefore also needs the services of the
10th (their 25:30 departures). That is a routing concern; this module only answers the per-date question.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.gtfs.spec import WEEKDAYS

REASON_WEEKLY = "weekly_calendar"
REASON_ADDED = "added_by_exception"
REASON_REMOVED = "removed_by_exception"
REASON_OUTSIDE_RANGE = "outside_calendar_date_range"
REASON_WEEKDAY_OFF = "weekday_not_scheduled"
REASON_NOT_ADDED = "not_added_on_this_date"  # defined only by calendar_dates, and not added on this date
REASON_UNDEFINED = "no_calendar_definition"  # referenced by trips only: neither calendar nor calendar_dates defines it


@dataclass(frozen=True)
class ServiceStatus:
    service_id: str
    active: bool
    reason: str


def to_gtfs_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def weekday_column(value: date) -> str:
    return WEEKDAYS[value.weekday()]  # fixed tuple: never user text, safe to interpolate


def evaluate_services(conn: sqlite3.Connection, service_date: date, *, include_trip_only: bool = True) -> list[ServiceStatus]:
    """Status and reason for every known service on ``service_date``, sorted by ``service_id``.

    "Known" = defined in ``calendar``/``calendar_dates`` and, when ``include_trip_only`` is set, also
    services referenced only by trips (reported inactive with ``no_calendar_definition``).
    """
    key, column = to_gtfs_date(service_date), weekday_column(service_date)
    base: dict[str, tuple[bool, str]] = {}
    for row in conn.execute(f"SELECT service_id, {column} AS on_day, start_date, end_date FROM calendar"):
        if not (row["start_date"] <= key <= row["end_date"]):
            base[row["service_id"]] = (False, REASON_OUTSIDE_RANGE)
        elif row["on_day"] == 1:
            base[row["service_id"]] = (True, REASON_WEEKLY)
        else:
            base[row["service_id"]] = (False, REASON_WEEKDAY_OFF)

    exceptions = {r["service_id"]: r["exception_type"]
                  for r in conn.execute("SELECT service_id, exception_type FROM calendar_dates WHERE date = ?", (key,))}
    dated_only = {r[0] for r in conn.execute("SELECT DISTINCT service_id FROM calendar_dates")} - set(base)
    known = set(base) | set(exceptions) | dated_only
    if include_trip_only:
        known |= {r[0] for r in conn.execute("SELECT DISTINCT service_id FROM trips")}

    result: list[ServiceStatus] = []
    for service_id in sorted(known):
        exception = exceptions.get(service_id)
        if exception == 1:
            result.append(ServiceStatus(service_id, True, REASON_ADDED))
        elif exception == 2:
            result.append(ServiceStatus(service_id, False, REASON_REMOVED))
        elif service_id in base:
            result.append(ServiceStatus(service_id, *base[service_id]))
        elif service_id in dated_only:
            result.append(ServiceStatus(service_id, False, REASON_NOT_ADDED))
        else:
            result.append(ServiceStatus(service_id, False, REASON_UNDEFINED))
    return result


def get_active_service_ids(conn: sqlite3.Connection, service_date: date) -> set[str]:
    """Service ids that run on ``service_date`` and no others."""
    return {s.service_id for s in evaluate_services(conn, service_date, include_trip_only=False) if s.active}
