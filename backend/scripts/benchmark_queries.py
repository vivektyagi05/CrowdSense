"""Measure representative GTFS queries on a real database (read-only) and print their query plans.

    python -m scripts.benchmark_queries                  # DATABASE_PATH from settings
    python -m scripts.benchmark_queries --database X.sqlite3 --runs 30 --markdown

Each query is run ``--runs`` times after one warm-up run; median and p95 wall times are reported, together with
``EXPLAIN QUERY PLAN``. Timings are for THIS machine and THIS database file; they are measurements, not guarantees.
The parameters (busiest stop, largest shape, largest route ...) are discovered from the data, never hard-coded.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from app.config import ConfigError, Settings
from app.db import open_connection


def _pick(conn, sql: str):
    row = conn.execute(sql).fetchone()
    return row[0] if row else None


def build_cases(conn):
    busiest_stop = _pick(conn, "SELECT stop_id FROM stop_times GROUP BY stop_id ORDER BY COUNT(*) DESC LIMIT 1")
    biggest_shape = _pick(conn, "SELECT shape_id FROM shapes ORDER BY point_count DESC LIMIT 1")
    biggest_route = _pick(conn, "SELECT route_id FROM trips GROUP BY route_id ORDER BY COUNT(*) DESC LIMIT 1")
    longest_trip = _pick(conn, "SELECT trip_id FROM stop_times GROUP BY trip_id ORDER BY COUNT(*) DESC LIMIT 1")
    a_trip = _pick(conn, "SELECT trip_id FROM trips LIMIT 1")
    service = _pick(conn, "SELECT service_id FROM calendar LIMIT 1")
    pair = conn.execute(
        "SELECT a.stop_id, b.stop_id FROM stop_times a JOIN stop_times b ON b.trip_id = a.trip_id AND b.stop_sequence = a.stop_sequence + 5 "
        "WHERE a.trip_id = ? AND a.stop_sequence = 1", (longest_trip,)).fetchone()
    return [
        ("stop name search (leading-wildcard LIKE)", "SELECT stop_id, stop_name FROM stops WHERE lower(stop_name) LIKE lower(?) ESCAPE '\\' ORDER BY stop_name, stop_id LIMIT 20", ("%chowk%",)),
        ("stop by primary key", "SELECT * FROM stops WHERE stop_id = ?", (busiest_stop,)),
        ("routes serving the busiest stop", "SELECT r.route_id, COUNT(*) FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id WHERE st.stop_id = ? GROUP BY r.route_id", (busiest_stop,)),
        ("next 20 departures, busiest stop (after 08:00, one service)",
         "SELECT st.trip_id, st.departure_time FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id WHERE st.stop_id = ? AND st.departure_time >= '08:00:00' AND t.service_id IN (?) ORDER BY st.departure_time, st.trip_id LIMIT 20", (busiest_stop, service)),
        ("stop_times of the longest trip (page of 100)", "SELECT st.stop_sequence, p.stop_name FROM stop_times st JOIN stops p ON p.stop_id = st.stop_id WHERE st.trip_id = ? ORDER BY st.stop_sequence LIMIT 100", (longest_trip,)),
        ("trip lookup by primary key", "SELECT * FROM trips WHERE trip_id = ?", (a_trip,)),
        ("all points of the largest shape", "SELECT shape_pt_lat, shape_pt_lon, shape_pt_sequence FROM shape_points WHERE shape_id = ? ORDER BY shape_pt_sequence", (biggest_shape,)),
        ("trips of the busiest route + first departure", "SELECT t.trip_id, (SELECT s.departure_time FROM stop_times s WHERE s.trip_id = t.trip_id ORDER BY s.stop_sequence LIMIT 1) AS fd FROM trips t WHERE t.route_id = ? ORDER BY fd, t.trip_id LIMIT 50", (biggest_route,)),
        ("distinct stops of the busiest route", "SELECT COUNT(DISTINCT st.stop_id) FROM trips t JOIN stop_times st ON st.trip_id = t.trip_id WHERE t.route_id = ?", (biggest_route,)),
        ("stops served by a route (stops?route_id=)", "SELECT stop_id FROM stops WHERE stop_id IN (SELECT st.stop_id FROM trips t JOIN stop_times st ON st.trip_id = t.trip_id WHERE t.route_id = ?) ORDER BY stop_name LIMIT 50", (biggest_route,)),
        ("trip count per service_id (full trips scan)", "SELECT service_id, COUNT(*) FROM trips GROUP BY service_id", ()),
        ("trips using one shape_id (no index on trips.shape_id)", "SELECT COUNT(*) FROM trips WHERE shape_id = ?", (biggest_shape,)),
        ("calendar lookup for a date", "SELECT service_id FROM calendar WHERE tuesday = 1 AND start_date <= ? AND end_date >= ?", ("20261110", "20261110")),
        ("Phase 0 direct journey (stop pair on the longest trip)",
         "SELECT t.trip_id, a.departure_time, b.arrival_time FROM stop_times a JOIN stop_times b ON b.trip_id = a.trip_id AND b.stop_sequence > a.stop_sequence JOIN trips t ON t.trip_id = a.trip_id WHERE a.stop_id = ? AND b.stop_id = ? AND t.service_id IN (?) AND a.departure_time >= '08:00:00' ORDER BY a.departure_time, a.trip_id LIMIT 10",
         (pair[0], pair[1], service) if pair else (None, None, service)),
    ]


def measure(conn, sql: str, params, runs: int):
    conn.execute(sql, params).fetchall()  # warm-up (page cache, statement cache)
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        rows = conn.execute(sql, params).fetchall()
        times.append((time.perf_counter() - started) * 1000)
    plan = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]
    times.sort()
    return statistics.median(times), times[max(0, int(len(times) * 0.95) - 1)], len(rows), plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.benchmark_queries", description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", type=Path)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table plus plans")
    args = parser.parse_args(argv)
    try:
        database = (args.database or Settings.from_env().database_path).resolve()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    with open_connection(database) as conn:
        results = [(name, *measure(conn, sql, params, args.runs)) for name, sql, params in build_cases(conn)]
    if args.markdown:
        print("| Query | median ms | p95 ms | rows |\n|---|---:|---:|---:|")
    for name, median, p95, rows, plan in results:
        print(f"| {name} | {median:.2f} | {p95:.2f} | {rows} |" if args.markdown else f"{median:8.2f} ms (p95 {p95:7.2f})  rows={rows:<5} {name}")
    print()
    for name, *_rest, plan in results:
        print(f"{name}")
        for step in plan:
            print(f"    {step}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
