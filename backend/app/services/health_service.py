"""Health reporting.

Four independent facts are reported and never conflated:

* application   - the process is up (trivially true if this code runs)
* database      - the SQLite file exists, opens and answers a query
* gtfs          - the expected tables/columns exist and hold data
* crowd_engine  - whether a crowd data source is connected (not yet: no ETM data)

The overall status is ``ok`` only when the database *and* GTFS data are ready.
Responses never include filesystem paths, SQL or raw exception text; details are
logged server-side instead.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from app.config import Settings
from app.db import DatabaseUnavailableError, open_connection
from app.gtfs.importer import read_import_status
from app.gtfs.schema import CORE_TABLES, EXPECTED_COLUMNS, SERVICE_TABLES
from app.schemas import ComponentStatus, GtfsCheck, HealthChecks, HealthResponse

logger = logging.getLogger(__name__)

# COUNT(*) over millions of rows is cheap but not free; cache per database *file state*.
_counts_cache: dict[tuple[str, int, int], dict[str, int]] = {}
_SETUP_HINT = "Run: python -m scripts.import_gtfs"


def _file_state(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _counts(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    key = _file_state(path)
    cached = _counts_cache.get(key)
    if cached is None:
        cached = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (*CORE_TABLES, *SERVICE_TABLES)}
        _counts_cache.clear()  # keep a single entry; the file changed
        _counts_cache[key] = cached
    return cached


def _import_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM import_meta")}
    except sqlite3.OperationalError:  # database predates import metadata
        return {}


def _gtfs_problems(conn: sqlite3.Connection) -> list[str]:
    problems: list[str] = []
    existing = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, columns in EXPECTED_COLUMNS.items():
        if table not in existing:
            problems.append(f"table '{table}' is missing")
            continue
        present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        absent = [c for c in columns if c not in present]
        if absent:
            problems.append(f"table '{table}' lacks column(s): {', '.join(absent)}")
    return problems


def _last_attempt(database: Path) -> dict | None:
    """Safe subset of the status file: no paths, no row-level error text."""
    status = read_import_status(database)
    if not status:
        return None
    return {k: status.get(k) for k in ("status", "phase", "started_at", "finished_at", "error_count") if k in status}


def check_gtfs(conn: sqlite3.Connection, database: Path) -> GtfsCheck:
    problems = _gtfs_problems(conn)
    attempt = _last_attempt(database)
    if problems:
        return GtfsCheck(status="not_ready", detail=f"GTFS tables are incomplete. {_SETUP_HINT}",
                         problems=problems, last_import_attempt=attempt)

    counts = _counts(conn, database)
    for table in CORE_TABLES:
        if counts[table] == 0:
            problems.append(f"table '{table}' is empty")
    if counts["calendar"] == 0 and counts["calendar_dates"] == 0:
        problems.append("no service calendar rows (calendar and calendar_dates are both empty)")
    meta = _import_meta(conn)
    common = dict(counts=counts, imported_at=meta.get("imported_at"), feed_version=meta.get("feed_version"),
                  feed_start_date=meta.get("feed_start_date"), feed_end_date=meta.get("feed_end_date"),
                  last_import_attempt=attempt)
    if problems:
        return GtfsCheck(status="not_ready", detail=f"GTFS data is incomplete. {_SETUP_HINT}",
                         problems=problems, **common)
    return GtfsCheck(status="ready", **common)


def build_health(settings: Settings) -> tuple[HealthResponse, int]:
    """Return the health document and the HTTP status code to serve it with."""
    application = ComponentStatus(status="ok")
    crowd = ComponentStatus(
        status="not_connected",
        detail="No crowd data source is connected; official ETM/e-ticketing records have not been obtained.")
    database: ComponentStatus
    gtfs: GtfsCheck
    overall: str
    path = settings.database_path

    if not path.is_file():
        database = ComponentStatus(status="missing", detail=f"Database file not found. {_SETUP_HINT}")
        gtfs = GtfsCheck(status="unknown", detail="Not evaluated: database unavailable.",
                         last_import_attempt=_last_attempt(path))
        overall = "needs_setup"
    else:
        try:
            with open_connection(path, check_same_thread=False) as conn:
                conn.execute("SELECT 1").fetchone()
                database = ComponentStatus(status="ok")
                gtfs = check_gtfs(conn, path)
            overall = "ok" if gtfs.status == "ready" else "needs_setup"
        except (DatabaseUnavailableError, sqlite3.Error):
            logger.exception("Health check: database could not be queried")
            database = ComponentStatus(status="error", detail="The database could not be opened or queried.")
            gtfs = GtfsCheck(status="unknown", detail="Not evaluated: database unavailable.")
            overall = "error"

    counts = gtfs.counts if gtfs.status == "ready" else None
    legacy_counts = {t: counts[t] for t in CORE_TABLES} if counts else None
    response = HealthResponse(
        status=overall,  # type: ignore[arg-type]
        version=__version__,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks=HealthChecks(application=application, database=database, gtfs=gtfs, crowd_engine=crowd),
        gtfs_loaded=gtfs.status == "ready",
        counts=legacy_counts,
        crowd_engine=crowd.status,
    )
    return response, 200 if overall == "ok" else 503
