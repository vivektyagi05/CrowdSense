"""Feed summary and the persisted validation report.

Row counts come from the ``import_meta`` record written inside the same transaction as the data, so they are exact for
*this* database file and cost nothing (no 2.4M-row COUNT per request). Everything else is a small bounded query.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.errors import AppError
from app.gtfs.importer import read_import_status
from app.schemas import AgencyOut, GtfsSummary, ValidationReport

DATA_SCOPE = {
    "static_schedule": "Planned timetable and network geometry published by the agency (GTFS Schedule).",
    "actual_vehicle_operations": "NOT included: no vehicle positions, delays, cancellations or breakdowns.",
    "passenger_ticket_data": "NOT included: no ETM / e-ticketing transactions.",
    "historical_passenger_load": "NOT included: derived only from ticket data, which has not been obtained.",
    "live_crowd_information": "NOT included: static GTFS says nothing about how full a bus is.",
}


def _meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM import_meta")}


def _json(meta: dict[str, str], key: str, default: Any) -> Any:
    try:
        return json.loads(meta[key])
    except (KeyError, ValueError):
        return default


def get_summary(conn: sqlite3.Connection) -> GtfsSummary:
    meta = _meta(conn)
    report = _json(meta, "import_report", {})
    counts = _json(meta, "table_counts", {})
    agencies = [AgencyOut(**dict(r)) for r in conn.execute("SELECT * FROM agency ORDER BY agency_name, agency_id")]
    feeds = [dict(r) for r in conn.execute("SELECT * FROM feed_info ORDER BY feed_info_id")]
    b = conn.execute("SELECT MIN(stop_lat), MIN(stop_lon), MAX(stop_lat), MAX(stop_lon) FROM stops WHERE stop_lat IS NOT NULL").fetchone()
    bounds = None if b[0] is None else {"min_lat": b[0], "min_lon": b[1], "max_lat": b[2], "max_lon": b[3]}
    by_type = {str(r[0]): r[1] for r in conn.execute("SELECT route_type, COUNT(*) FROM routes GROUP BY route_type ORDER BY 1")}
    cal = conn.execute("SELECT COUNT(*), MIN(start_date), MAX(end_date) FROM calendar").fetchone()
    exceptions = conn.execute("SELECT COUNT(*), COALESCE(SUM(exception_type = 1), 0), COALESCE(SUM(exception_type = 2), 0) FROM calendar_dates").fetchone()
    trips_by_service = {r[0]: r[1] for r in conn.execute("SELECT service_id, COUNT(*) FROM trips GROUP BY service_id")}
    shape = conn.execute("SELECT COUNT(*), COALESCE(SUM(point_count), 0), MIN(point_count), MAX(point_count) FROM shapes").fetchone()
    with_shape = conn.execute("SELECT COUNT(*) FROM trips WHERE shape_id IS NOT NULL").fetchone()[0]
    dq = report.get("data_quality")
    return GtfsSummary(
        schema_version=int(meta.get("schema_version", 1)), imported_at=meta.get("imported_at"),
        source_zip_name=meta.get("source_zip_name"), source_sha256=meta.get("source_sha256"),
        feed=feeds, agencies=agencies, counts=counts, bounds=bounds, routes_by_type=by_type,
        calendar={"services_in_calendar": cal[0], "first_start_date": cal[1], "last_end_date": cal[2],
                  "exception_rows": exceptions[0], "added_exceptions": exceptions[1], "removed_exceptions": exceptions[2],
                  "calendar_dates_present": exceptions[0] > 0, "trips_by_service": trips_by_service},
        shapes={"shape_count": shape[0], "point_count": shape[1], "min_points_per_shape": shape[2], "max_points_per_shape": shape[3],
                "trips_with_shape": with_shape, "trips_total": sum(trips_by_service.values())},
        data_quality=None if dq is None else {k: dq[k] for k in ("status", "error_count", "warning_count", "info_count")},
        data_scope=DATA_SCOPE)


def get_validation_report(conn: sqlite3.Connection, database: Path) -> ValidationReport:
    meta = _meta(conn)
    report = _json(meta, "import_report", None)
    if report is None:
        raise AppError(404, "report_not_available", "This database holds no validation report. Re-run the GTFS import.")
    attempt = read_import_status(database)
    safe = None
    if attempt:
        safe = {k: attempt.get(k) for k in ("status", "phase", "message", "started_at", "finished_at", "duration_seconds",
                                            "error_count", "promoted") if k in attempt}
    return ValidationReport(
        schema_version=int(meta.get("schema_version", 1)), imported_at=meta.get("imported_at"),
        source_sha256=meta.get("source_sha256"), data_quality=report.get("data_quality"),
        files=report.get("file_details", []), missing_optional_files=report.get("missing_optional_files", []),
        recognised_unimported_files=report.get("recognised_unimported_files", []),
        unrecognised_files=report.get("unrecognised_files", []), column_usage=report.get("column_usage", {}),
        last_import_attempt=safe)
