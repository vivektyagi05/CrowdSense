"""Safe, staged GTFS import.

Flow
----
1. Take an exclusive import lock (``<db>.import.lock``).
2. Validate the archive (files, headers, CRCs) - no database work yet.
3. Build a brand-new *staging* database next to the live one, in ONE transaction:
   strict row validation -> duplicate check -> indexes -> referential checks.
   Any failure rolls back and discards the staging file.
4. Commit, switch to WAL, checkpoint, fsync, ``quick_check`` and re-count from disk.
5. Promote: checkpoint the live database so no WAL/SHM sidecar can be carried
   over, hard-link it to ``<db>.previous``, then atomically ``os.replace`` the
   staging file over it. Verify the promoted file; if verification fails the
   previous database is restored.

The live database is never modified, truncated or deleted before a fully
validated replacement exists. A failed import leaves it byte-for-byte intact.

A fresh staging database per run is what makes imports repeatable: there is
nothing to de-duplicate against, so re-importing can never create duplicate rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import open_connection, sqlite_uri, transaction
from app.gtfs import validation
from app.gtfs.archive import GtfsArchive, inspect_archive
from app.gtfs.errors import (
    GtfsArchiveError,
    GtfsDataError,
    GtfsImportError,
    ImportLockedError,
    PromotionError,
)
from app.gtfs.loader import DEFAULT_BATCH_SIZE, LOAD_ORDER, TABLE_FILENAMES, ErrorCollector, load_table
from app.gtfs.schema import CORE_TABLES, INDEXES_DDL, SCHEMA_VERSION, TABLES_DDL, UNIQUE_INDEXES_DDL
from app.gtfs.validation import QualityReport

logger = logging.getLogger(__name__)

SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
SHRINK_WARNING_RATIO = 0.5


# ---------------------------------------------------------------------------
# Paths and report
# ---------------------------------------------------------------------------

def staging_path(database: Path) -> Path:
    return database.with_name(database.name + ".staging")


def previous_path(database: Path) -> Path:
    return database.with_name(database.name + ".previous")


def lock_path(database: Path) -> Path:
    return database.with_name(database.name + ".import.lock")


def status_path(database: Path) -> Path:
    return database.with_name(database.name + ".import-status.json")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ImportReport:
    """Everything worth knowing about one import attempt."""

    status: str = "failed"  # success | validated (dry run) | failed
    phase: str = "starting"
    message: str | None = None
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    source_zip: str = ""
    source_sha256: str | None = None
    source_size_bytes: int | None = None
    database: str = ""
    promoted: bool = False
    previous_database: str | None = None
    gtfs_root: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    ignored_files: list[str] = field(default_factory=list)
    feed_info: dict[str, str] | None = None
    counts: dict[str, int] = field(default_factory=dict)  # the six Phase 0 tables (kept for compatibility)
    previous_counts: dict[str, int] | None = None
    warnings: list[str] = field(default_factory=list)
    error_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    # --- Phase 1 -------------------------------------------------------------------------------
    schema_version: int = SCHEMA_VERSION
    table_counts: dict[str, int] = field(default_factory=dict)  # every GTFS table
    file_details: list[dict[str, Any]] = field(default_factory=list)  # per-file row accounting and columns
    missing_optional_files: list[str] = field(default_factory=list)
    recognised_unimported_files: list[str] = field(default_factory=list)  # valid GTFS files this phase skips
    unrecognised_files: list[str] = field(default_factory=list)
    column_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    data_quality: dict[str, Any] | None = None  # findings + integrity checks; separate from ``status``
    staging_build_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Lock and status file
# ---------------------------------------------------------------------------

class _ImportLock:
    """Cross-process mutual exclusion via an exclusively created lock file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                holder = "unknown"
            raise ImportLockedError(
                f"Another GTFS import appears to be running (lock file {self.path.name}: {holder}). "
                f"If no import is running, delete that file and retry.", phase="locking") from None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": _utcnow()}))
        self._held = True

    def release(self) -> None:
        if self._held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._held = False


def write_import_status(database: Path, report: ImportReport) -> None:
    """Atomically persist the outcome of the latest import attempt."""
    target = status_path(database)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        logger.exception("Could not write import status file %s", target.name)


def read_import_status(database: Path) -> dict[str, Any] | None:
    """Return the last import attempt record, or ``None`` if absent/unreadable."""
    try:
        return json.loads(status_path(database).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _remove_database_files(path: Path) -> None:
    for candidate in (path, *(path.with_name(path.name + s) for s in SIDECAR_SUFFIXES)):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _execute_script(conn: sqlite3.Connection, script: str) -> None:
    # executescript() would COMMIT the surrounding transaction, so run statements one by one.
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _read_counts(database: Path) -> dict[str, int] | None:
    try:
        with open_connection(database) as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in CORE_TABLES}
    except Exception:  # an unreadable/legacy database simply has no comparable counts
        return None


# ---------------------------------------------------------------------------
# Staging build
# ---------------------------------------------------------------------------

def _build_staging(archive: GtfsArchive, staging: Path, report: ImportReport, batch_size: int) -> dict[str, int]:
    """Create and fully validate the staging database. Returns the committed Phase 0 table counts.

    The complete counts of every GTFS table are stored in ``report.table_counts``.
    """
    _remove_database_files(staging)
    build_started = time.monotonic()
    conn = sqlite3.connect(staging, isolation_level=None)
    try:
        # The staging database is disposable: favour speed during the load, then
        # make it durable (fsync) before it is ever promoted.
        conn.execute("PRAGMA journal_mode = MEMORY")  # keeps ROLLBACK well defined
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA foreign_keys = OFF")  # verified set-based below
        conn.execute("PRAGMA cache_size = -262144")  # 256 MiB page cache
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")

        errors = ErrorCollector()
        quality = QualityReport()
        loaded: dict[str, int] = {}
        with transaction(conn):
            _execute_script(conn, TABLES_DDL)

            report.phase = "loading"
            with zipfile.ZipFile(archive.zip_path) as zf:
                for table in LOAD_ORDER:
                    filename = TABLE_FILENAMES[table]
                    if filename not in archive.members:
                        loaded[table] = 0  # optional file absent
                        continue
                    stats = load_table(conn, zf, archive, table, errors, batch_size=batch_size)
                    loaded[table] = stats.rows_imported
                    report.file_details.append({
                        "file": filename, "table": table, "member": archive.members[filename],
                        "rows_read": stats.rows_read, "rows_imported": stats.rows_imported,
                        "rows_rejected": stats.rows_rejected, "columns": archive.column_report.get(filename, {}),
                    })
            _raise_if_errors(errors, "GTFS data failed validation while loading")

            report.phase = "validating"
            validation.check_duplicate_keys(conn, quality)
            _raise_if_quality_errors(quality, report, "GTFS data contains duplicate keys")

            _execute_script(conn, UNIQUE_INDEXES_DDL)
            loaded["shapes"] = validation.build_shapes_summary(conn)
            _execute_script(conn, INDEXES_DDL)
            table_counts = validation.check_row_counts(conn, loaded, quality)
            validation.run_integrity_checks(conn, quality)
            report.column_usage = validation.column_usage(conn)
            validation.describe_extensions(report.column_usage, archive.column_report, quality)
            _archive_findings(archive, quality)
            _raise_if_quality_errors(quality, report, "GTFS data failed integrity validation")

            report.table_counts = table_counts
            report.data_quality = quality.to_dict()
            report.warnings.extend(f.message for f in quality.of("warning"))
            report.feed_info = _first_feed_info(conn)
            _write_meta(conn, archive, report, {t: table_counts[t] for t in LEGACY_TABLES})
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        # transaction committed here

        report.phase = "finalizing"
        conn.execute("PRAGMA locking_mode = NORMAL")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")  # drop the exclusive lock
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")  # persistent; matches the API's expectations
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if not validation.quick_check(conn):
            raise GtfsDataError("SQLite quick_check failed on the staging database", phase="finalizing",
                                errors=[{"file": staging.name, "line": None, "message": "quick_check failed"}])
    finally:
        conn.close()

    _fsync(staging)
    leftovers = [s for s in SIDECAR_SUFFIXES if staging.with_name(staging.name + s).exists()]
    if leftovers:
        raise GtfsDataError(f"Staging database still has sidecar files {leftovers} after close", phase="finalizing",
                            errors=[{"file": staging.name, "line": None, "message": f"unexpected sidecars {leftovers}"}])
    report.staging_build_seconds = round(time.monotonic() - build_started, 2)
    return {t: table_counts[t] for t in LEGACY_TABLES}


LEGACY_TABLES = ("stops", "routes", "trips", "stop_times", "calendar", "calendar_dates")


def _archive_findings(archive: GtfsArchive, quality: QualityReport) -> None:
    """Facts about the archive itself, expressed in the same finding vocabulary as the data checks."""
    for name in archive.missing_optional_files:
        quality.info("optional_file_absent", f"optional file {name} is not in the feed (nothing was invented)", file=name)
    for name in archive.ignored_known_files:
        quality.warn("recognised_file_not_imported", f"{name} is a valid GTFS file but this version does not import it",
                     file=name)
    for name in archive.unrecognised_files:
        quality.warn("unrecognised_file", f"{name} is not a GTFS Schedule file and was ignored", file=name)


def _first_feed_info(conn: sqlite3.Connection) -> dict[str, str] | None:
    row = conn.execute("SELECT feed_publisher_name, feed_version, feed_start_date, feed_end_date FROM feed_info "
                       "ORDER BY feed_info_id LIMIT 1").fetchone()
    if row is None:
        return None
    info = dict(zip(("feed_publisher_name", "feed_version", "feed_start_date", "feed_end_date"), row))
    return {k: v for k, v in info.items() if v}


def _raise_if_errors(errors: ErrorCollector, message: str) -> None:
    if errors:
        raise GtfsDataError(f"{message}: {errors.total:,} problem(s)", phase="data_validation",
                            errors=list(errors.samples), total_errors=errors.total)


def _raise_if_quality_errors(quality: QualityReport, report: ImportReport, message: str) -> None:
    problems = quality.of("error")
    if problems:
        report.data_quality = quality.to_dict()  # keep the full picture on the failed report
        records = [{"file": f.file or "", "line": None, "code": f.code, "message": f.message} for f in problems]
        raise GtfsDataError(f"{message}: {len(problems):,} problem(s)", phase="data_validation", errors=records[:50],
                            total_errors=len(problems))


def _write_meta(conn: sqlite3.Connection, archive: GtfsArchive, report: ImportReport, counts: dict[str, int]) -> None:
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "imported_at": _utcnow(),
        "source_zip_name": archive.zip_path.name,
        "source_sha256": report.source_sha256 or "",
        "source_size_bytes": str(report.source_size_bytes or 0),
        "gtfs_root": archive.root,
        "counts": json.dumps(counts, sort_keys=True),
        "table_counts": json.dumps(report.table_counts, sort_keys=True),
        # The data-quality picture of *this* database, kept inside it so it can never drift from the data.
        "import_report": json.dumps({
            "imported_at": None,  # filled by readers from the 'imported_at' key
            "file_details": report.file_details,
            "missing_optional_files": list(archive.missing_optional_files),
            "recognised_unimported_files": list(archive.ignored_known_files),
            "unrecognised_files": list(archive.unrecognised_files),
            "column_usage": report.column_usage,
            "data_quality": report.data_quality,
        }, sort_keys=True),
    }
    for key, value in (report.feed_info or {}).items():
        meta[key] = value
    conn.executemany("INSERT INTO import_meta(key, value) VALUES (?, ?)", sorted(meta.items()))


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

class _DatabaseBusy(Exception):
    """The live database is still held open by another connection."""


def _quiesce(database: Path) -> None:
    """Fold the live database's WAL into the main file and prove no sidecars remain.

    Replacing the main file while a ``-wal``/``-shm`` from the *old* database
    still exists would let SQLite apply stale frames to the *new* file. After a
    successful TRUNCATE checkpoint and close by the last connection, SQLite
    removes both sidecars; if they survive, someone else still has it open.
    """
    try:
        conn = sqlite3.connect(sqlite_uri(database, "rw"), uri=True, timeout=1.0, isolation_level=None)
    except sqlite3.Error as exc:
        raise _DatabaseBusy(f"cannot open live database: {exc}") from exc
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() == "wal":
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
            if busy:
                raise _DatabaseBusy("WAL checkpoint was blocked by another connection")
    except sqlite3.Error as exc:
        raise _DatabaseBusy(f"cannot checkpoint live database: {exc}") from exc
    finally:
        conn.close()
    leftovers = [s for s in ("-wal", "-shm") if database.with_name(database.name + s).exists()]
    if leftovers:
        raise _DatabaseBusy(f"live database still has active sidecar files {leftovers}")


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    try:
        os.link(source, target)  # instant, no extra disk; same inode until the swap
    except OSError:
        shutil.copy2(source, target)  # filesystems without hard links


def _swap_in(staging: Path, database: Path, *, retries: int, delay: float) -> bool:
    """Atomically put ``staging`` in place of ``database``. Returns True if a previous DB was kept."""
    previous = previous_path(database)
    candidate = previous.with_name(previous.name + ".tmp")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        had_live = database.exists()
        try:
            if had_live:
                _quiesce(database)
                _link_or_copy(database, candidate)
            os.replace(staging, database)  # atomic on POSIX and Windows
        except (_DatabaseBusy, PermissionError) as exc:  # Windows refuses to replace an open file
            last_error = exc
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            if attempt < retries:
                logger.warning("Database busy (%s); retry %d/%d", exc, attempt + 1, retries)
                time.sleep(delay)
            continue
        if had_live:
            for suffix in ("-wal", "-shm"):
                _remove_quietly(previous.with_name(previous.name + suffix))
            os.replace(candidate, previous)
        return had_live
    raise PromotionError(
        "The live database is in use, so it was not replaced. The previous database is untouched. "
        "Stop the API server (or any program holding the database open) and run the import again. "
        f"Last error: {last_error}", phase="promotion",
        errors=[{"file": database.name, "line": None, "message": str(last_error)}])


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _verify_promoted(database: Path, expected: dict[str, int]) -> None:
    with open_connection(database) as conn:
        actual = validation.all_table_counts(conn) if set(expected) - set(validation.ALL_TABLES) else validation.table_counts(conn)
        if actual != expected:
            raise PromotionError("Promoted database counts do not match the validated staging counts",
                                 phase="promotion",
                                 errors=[{"file": database.name, "line": None,
                                          "message": f"expected {expected}, found {actual}"}])
        if not validation.quick_check(conn):
            raise PromotionError("Promoted database failed quick_check", phase="promotion",
                                 errors=[{"file": database.name, "line": None, "message": "quick_check failed"}])


def _promote(staging: Path, database: Path, counts: dict[str, int], report: ImportReport,
             *, retries: int, delay: float) -> None:
    report.phase = "promotion"
    if database.exists():
        report.previous_counts = _read_counts(database)
        if report.previous_counts:
            for table in CORE_TABLES:
                old, new = report.previous_counts.get(table, 0), counts.get(table, 0)
                if old and new < old * SHRINK_WARNING_RATIO:
                    report.warnings.append(
                        f"{table} shrank from {old:,} to {new:,} rows (> {int((1 - SHRINK_WARNING_RATIO) * 100)}% drop); "
                        f"the previous database is kept as {previous_path(database).name}")
    kept_previous = _swap_in(staging, database, retries=retries, delay=delay)
    try:
        _verify_promoted(database, report.table_counts or counts)
    except Exception:
        logger.exception("Post-promotion verification failed; restoring previous database")
        _remove_database_files(database)
        if kept_previous:
            os.replace(previous_path(database), database)
        raise
    report.promoted = True
    report.previous_database = previous_path(database).name if kept_previous else None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def import_gtfs(
    zip_path: Path,
    database_path: Path,
    *,
    validate_only: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    promote_retries: int = 10,
    promote_retry_delay: float = 0.5,
) -> ImportReport:
    """Import ``zip_path`` into ``database_path`` safely.

    Returns the :class:`ImportReport` on success. On failure raises a
    :class:`GtfsImportError` subclass whose ``.report`` holds the same record;
    in both cases the outcome is also written to ``<db>.import-status.json``.
    The existing database is only ever replaced by a fully validated one.
    """
    zip_path, database_path = Path(zip_path), Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    report = ImportReport(source_zip=str(zip_path), database=str(database_path), started_at=_utcnow())
    started = time.monotonic()
    staging = staging_path(database_path)

    lock = _ImportLock(lock_path(database_path))
    lock.acquire()  # raises ImportLockedError; deliberately does not touch the status file
    logger.info("GTFS import started: zip=%s database=%s validate_only=%s", zip_path.name, database_path.name, validate_only)
    try:
        try:
            report.phase = "archive_validation"
            archive = inspect_archive(zip_path)
            report.gtfs_root = archive.root or "(zip root)"
            report.files = dict(archive.members)
            report.ignored_files = list(archive.ignored_known_files)
            report.recognised_unimported_files = list(archive.ignored_known_files)
            report.missing_optional_files = list(archive.missing_optional_files)
            report.unrecognised_files = list(archive.unrecognised_files)
            report.warnings.extend(archive.warnings)
            report.source_size_bytes = zip_path.stat().st_size
            report.source_sha256 = _sha256(zip_path)
            logger.info("Archive OK: GTFS root=%s, %d file(s) to import", report.gtfs_root, len(archive.members))

            _remove_quietly(previous_path(database_path).with_name(previous_path(database_path).name + ".tmp"))
            counts = _build_staging(archive, staging, report, batch_size)
            report.counts = counts

            if validate_only:
                report.status = "validated"
                report.message = "Validation succeeded; database was NOT modified (--validate-only)."
            else:
                _promote(staging, database_path, counts, report,
                         retries=promote_retries, delay=promote_retry_delay)
                report.status = "success"
                report.message = "Import succeeded and the new database was promoted."
            report.phase = "complete"
        except GtfsImportError as exc:
            _record_failure(report, exc.phase, exc.message, exc.errors, exc.total_errors)
            exc.report = report
            raise
        except KeyboardInterrupt:
            _record_failure(report, report.phase, "Import interrupted by user; database untouched", [], 0)
            raise
        except Exception as exc:  # unexpected: never hide it, but never leak it either
            logger.exception("Unexpected error during GTFS import")
            _record_failure(report, report.phase, f"Unexpected {type(exc).__name__} during import; "
                            "the existing database was not modified. See the log for details.", [], 0)
            wrapped = GtfsImportError(report.message or "unexpected error", phase=report.phase)
            wrapped.report = report
            raise wrapped from exc
        finally:
            report.finished_at = _utcnow()
            report.duration_seconds = round(time.monotonic() - started, 2)
            write_import_status(database_path, report)
    finally:
        _remove_database_files(staging)
        lock.release()

    logger.info("GTFS import %s in %.1fs: %s", report.status, report.duration_seconds, report.counts)
    return report


def _record_failure(report: ImportReport, phase: str, message: str, errors: list[dict[str, Any]],
                    total_errors: int) -> None:
    report.status = "failed"
    report.phase = phase
    report.message = message
    report.errors = errors
    report.error_count = total_errors
    report.promoted = False
    logger.error("GTFS import failed in phase %s: %s", phase, message)
    for record in errors[:10]:
        logger.error("  %s", record)
