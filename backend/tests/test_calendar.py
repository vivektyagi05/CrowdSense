"""Service-date evaluation. Deterministic: fixed dates, no clock. 2026-11-09 is a Monday."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.gtfs import calendar as cal
from app.gtfs.calendar import evaluate_services, get_active_service_ids
from app.gtfs.schema import TABLES_DDL

MON, TUE, WED, SAT, SUN = (date(2026, 11, d) for d in (9, 10, 11, 14, 15))


def make_db(calendar=(), dates=(), trips=()) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in TABLES_DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.executemany("INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)", calendar)
    conn.executemany("INSERT INTO calendar_dates VALUES (?,?,?)", dates)
    conn.execute("INSERT INTO routes(route_id, route_short_name, route_type) VALUES ('R','1',3)")
    conn.executemany("INSERT INTO trips(trip_id, route_id, service_id) VALUES (?, 'R', ?)", trips)
    return conn


WEEKDAYS_ONLY = ("WK", 1, 1, 1, 1, 1, 0, 0, "20261101", "20261130")
WEEKEND_ONLY = ("WE", 0, 0, 0, 0, 0, 1, 1, "20261101", "20261130")


def test_weekday_and_weekend_services_run_on_the_right_days():
    conn = make_db([WEEKDAYS_ONLY, WEEKEND_ONLY])
    assert get_active_service_ids(conn, MON) == {"WK"}
    assert get_active_service_ids(conn, WED) == {"WK"}
    assert get_active_service_ids(conn, SAT) == {"WE"}
    assert get_active_service_ids(conn, SUN) == {"WE"}


def test_calendar_range_is_inclusive_at_both_ends():
    conn = make_db([("S", 1, 1, 1, 1, 1, 1, 1, "20261110", "20261112")])
    assert get_active_service_ids(conn, date(2026, 11, 9)) == set()
    assert get_active_service_ids(conn, date(2026, 11, 10)) == {"S"}
    assert get_active_service_ids(conn, date(2026, 11, 12)) == {"S"}
    assert get_active_service_ids(conn, date(2026, 11, 13)) == set()


def test_added_exception_activates_a_service_on_a_normally_inactive_day():
    conn = make_db([WEEKDAYS_ONLY, WEEKEND_ONLY], [("WE", "20261109", 1)])
    assert get_active_service_ids(conn, MON) == {"WK", "WE"}
    assert get_active_service_ids(conn, TUE) == {"WK"}  # the exception is for one date only


def test_removed_exception_deactivates_a_running_service():
    conn = make_db([WEEKDAYS_ONLY], [("WK", "20261110", 2)])
    assert get_active_service_ids(conn, MON) == {"WK"}
    assert get_active_service_ids(conn, TUE) == set()
    assert get_active_service_ids(conn, WED) == {"WK"}


def test_added_exception_works_outside_the_calendar_range():
    conn = make_db([WEEKDAYS_ONLY], [("WK", "20261205", 1)])  # a Saturday, after end_date
    assert get_active_service_ids(conn, date(2026, 12, 5)) == {"WK"}
    assert get_active_service_ids(conn, date(2026, 12, 4)) == set()


def test_removing_a_service_that_was_not_running_changes_nothing():
    conn = make_db([WEEKDAYS_ONLY], [("WK", "20261114", 2)])  # Saturday: WK is already off
    assert get_active_service_ids(conn, SAT) == set()


def test_calendar_dates_only_feed_has_no_service_except_on_added_dates():
    conn = make_db(dates=[("D", "20261111", 1), ("D", "20261112", 1)])
    assert get_active_service_ids(conn, WED) == {"D"}
    assert get_active_service_ids(conn, TUE) == set()


def test_feed_without_calendar_dates_never_assumes_exceptions():
    conn = make_db([WEEKDAYS_ONLY])
    assert get_active_service_ids(conn, TUE) == {"WK"}


def test_trips_are_not_assumed_to_run_every_day():
    conn = make_db([WEEKEND_ONLY], trips=[("T1", "WE"), ("T2", "ORPHAN")])
    assert get_active_service_ids(conn, MON) == set()


def test_reasons_explain_every_decision():
    conn = make_db([WEEKDAYS_ONLY, WEEKEND_ONLY, ("OLD", 1, 1, 1, 1, 1, 1, 1, "20200101", "20201231")],
                   [("WE", "20261109", 1), ("WK", "20261110", 2), ("DATED", "20261201", 1)], trips=[("T", "ORPHAN")])
    on_monday = {s.service_id: (s.active, s.reason) for s in evaluate_services(conn, MON)}
    assert on_monday == {"WK": (True, cal.REASON_WEEKLY), "WE": (True, cal.REASON_ADDED),
                         "OLD": (False, cal.REASON_OUTSIDE_RANGE), "ORPHAN": (False, cal.REASON_UNDEFINED),
                         "DATED": (False, cal.REASON_NOT_ADDED)}
    on_tuesday = {s.service_id: s.reason for s in evaluate_services(conn, TUE)}
    assert on_tuesday["WK"] == cal.REASON_REMOVED and on_tuesday["WE"] == cal.REASON_WEEKDAY_OFF


def test_trip_only_services_can_be_left_out_of_the_evaluation():
    conn = make_db([WEEKDAYS_ONLY], trips=[("T", "ORPHAN")])
    assert {s.service_id for s in evaluate_services(conn, MON, include_trip_only=False)} == {"WK"}
    assert {s.service_id for s in evaluate_services(conn, MON)} == {"WK", "ORPHAN"}


@pytest.mark.parametrize("day,expected", [(date(2026, 11, 9), "monday"), (date(2026, 11, 15), "sunday")])
def test_weekday_column_mapping(day, expected):
    assert cal.weekday_column(day) == expected
