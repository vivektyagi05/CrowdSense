"""Post-load validation, executed on the staging database before it is committed.

Everything here is set-based SQL: no table is ever pulled into Python memory.

Findings have three severities, kept strictly apart:

``error``    the data violates the GTFS specification in a way that makes the feed unsafe to use.
             Any error aborts the import; the live database is never replaced.
``warning``  suspicious or spec-discouraged data that does not prevent correct use. Recorded, never hidden.
``info``     neutral facts worth knowing (extension columns, overnight service, populated optional fields).

Every integrity check - passed or failed - is recorded, so the report states what was verified, not
only what went wrong.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from app.gtfs.schema import ALL_TABLES, CORE_TABLES, GTFS_TABLES
from app.gtfs.spec import REFERENCES, SPEC_BY_TABLE, TABLE_SPECS

logger = logging.getLogger(__name__)

SAMPLE_SIZE = 5
SEVERITIES = ("error", "warning", "info")


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # error | warning | info
    code: str
    message: str
    file: str | None = None
    count: int | None = None
    examples: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    code: str
    description: str
    severity: str  # severity a violation would have
    status: str  # passed | failed | skipped
    violations: int = 0
    note: str | None = None


class QualityReport:
    """Collects findings and check outcomes of one validation run."""

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.checks: list[CheckResult] = []

    # -- recording ---------------------------------------------------------
    def check(self, code: str, description: str, severity: str, violations: int, *, file: str | None = None,
              examples: Sequence[Any] = (), message: str | None = None) -> bool:
        """Record a check. Returns ``True`` when it passed."""
        if violations == 0:
            self.checks.append(CheckResult(code, description, severity, "passed"))
            return True
        text = message or f"{violations:,} {description}"
        if examples:
            text += " (e.g. " + ", ".join(repr(e) if isinstance(e, str) else str(e) for e in examples) + ")"
        self.checks.append(CheckResult(code, description, severity, "failed", violations))
        self.findings.append(Finding(severity, code, text, file, violations, [str(e) for e in examples]))
        return False

    def skipped(self, code: str, description: str, reason: str) -> None:
        self.checks.append(CheckResult(code, description, "error", "skipped", 0, reason))

    def info(self, code: str, message: str, *, file: str | None = None, count: int | None = None) -> None:
        self.findings.append(Finding("info", code, message, file, count))

    def warn(self, code: str, message: str, *, file: str | None = None, count: int | None = None) -> None:
        self.findings.append(Finding("warning", code, message, file, count))

    def error(self, code: str, message: str, *, file: str | None = None, count: int | None = None) -> None:
        self.findings.append(Finding("error", code, message, file, count))

    # -- queries -----------------------------------------------------------
    def of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "fail"
        return "pass_with_warnings" if self.of("warning") else "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error_count": len(self.of("error")),
            "warning_count": len(self.of("warning")),
            "info_count": len(self.of("info")),
            "findings": [asdict(f) for f in self.findings],
            "integrity_checks": [asdict(c) for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Small SQL helpers
# ---------------------------------------------------------------------------

def _scalar(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


def _examples(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[str]:
    return [str(r[0]) for r in conn.execute(f"{sql} LIMIT {SAMPLE_SIZE}", params)]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts of the six Phase 0 tables (kept for report/health compatibility)."""
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ALL_TABLES}


def all_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts of every GTFS table in the Phase 1 schema."""
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in GTFS_TABLES}


def quick_check(conn: sqlite3.Connection) -> bool:
    return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


# ---------------------------------------------------------------------------
# Checks that must run BEFORE unique indexes are built
# ---------------------------------------------------------------------------

def check_duplicate_keys(conn: sqlite3.Connection, qr: QualityReport) -> None:
    """GTFS requires ``(trip_id, stop_sequence)`` and ``(shape_id, shape_pt_sequence)`` to be unique."""
    for code, table, file, a, b in (
        ("duplicate_stop_time_sequence", "stop_times", "stop_times.txt", "trip_id", "stop_sequence"),
        ("duplicate_shape_point_sequence", "shape_points", "shapes.txt", "shape_id", "shape_pt_sequence"),
    ):
        groups = f"FROM {table} GROUP BY {a}, {b} HAVING COUNT(*) > 1"
        total = _scalar(conn, f"SELECT COUNT(*) FROM (SELECT 1 {groups})")
        examples = [f"({a}={r[0]!r}, {b}={r[1]})" for r in conn.execute(f"SELECT {a}, {b} {groups} LIMIT {SAMPLE_SIZE}")]
        qr.check(code, f"duplicate ({a}, {b}) pair(s) in {file}", "error", total, file=file, examples=examples)


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------

def check_references(conn: sqlite3.Connection, qr: QualityReport) -> None:
    """Every declared GTFS relationship, verified with an anti-join."""
    for ref in REFERENCES:
        child, parent = SPEC_BY_TABLE.get(ref.child), SPEC_BY_TABLE.get(ref.parent)
        child_file = child.filename if child else f"{ref.child}.txt"
        description = ref.description
        if _scalar(conn, f"SELECT COUNT(*) FROM {ref.child}") == 0:
            qr.skipped(ref.code, description, f"{ref.child} has no rows")
            continue
        if ref.parent_optional and _scalar(conn, f"SELECT COUNT(*) FROM {ref.parent}") == 0:
            qr.skipped(ref.code, description, f"{ref.parent} has no rows (file absent); references cannot be verified")
            continue
        where = (f"FROM {ref.child} c WHERE c.{ref.child_column} IS NOT NULL AND NOT EXISTS "
                 f"(SELECT 1 FROM {ref.parent} p WHERE p.{ref.parent_column} = c.{ref.child_column})")
        count = _scalar(conn, f"SELECT COUNT(*) {where}")
        examples = _examples(conn, f"SELECT DISTINCT c.{ref.child_column} {where}") if count else []
        qr.check(ref.code, description, ref.severity, count, file=child_file, examples=examples)

    # service_id may live in calendar OR calendar_dates, so it cannot be a plain foreign key
    where = ("FROM trips t WHERE t.service_id NOT IN (SELECT service_id FROM calendar) "
             "AND t.service_id NOT IN (SELECT service_id FROM calendar_dates)")
    count = _scalar(conn, f"SELECT COUNT(*) {where}")
    examples = _examples(conn, f"SELECT DISTINCT t.service_id {where}") if count else []
    qr.check("trip_service_missing", "trips reference a service_id found in neither calendar.txt nor calendar_dates.txt",
             "error", count, file="trips.txt", examples=examples)


# ---------------------------------------------------------------------------
# Schema-level consistency
# ---------------------------------------------------------------------------

def check_row_counts(conn: sqlite3.Connection, loaded: dict[str, int], qr: QualityReport) -> dict[str, int]:
    """Every parsed row must be present, and the core tables must not be empty."""
    counts = all_table_counts(conn)
    mismatches = [f"{t}: loaded {n:,} but table holds {counts[t]:,}" for t, n in loaded.items() if counts[t] != n]
    qr.check("row_counts_match", "tables hold a different number of rows than were parsed", "error", len(mismatches),
             examples=mismatches)
    empty = [t for t in CORE_TABLES if counts[t] == 0]
    qr.check("core_tables_not_empty", "core tables contain no rows", "error", len(empty),
             message=f"core table(s) contain no rows: {', '.join(empty)}", examples=[])
    return counts


def check_agency_and_feed(conn: sqlite3.Connection, qr: QualityReport) -> None:
    agencies = _scalar(conn, "SELECT COUNT(*) FROM agency")
    if agencies == 0:
        qr.warn("agency_file_missing",
                "agency.txt is absent or empty; the GTFS specification requires it. Agency names are unavailable.",
                file="agency.txt")
    else:
        zones = [r[0] for r in conn.execute("SELECT DISTINCT agency_timezone FROM agency ORDER BY 1")]
        qr.check("agency_timezone_consistent", "distinct agency_timezone values (GTFS requires a single timezone)",
                 "error", len(zones) - 1 if len(zones) > 1 else 0, file="agency.txt", examples=zones,
                 message=f"agencies declare different timezones: {', '.join(zones)}")
        if agencies > 1:
            missing = _scalar(conn, "SELECT COUNT(*) FROM routes WHERE agency_id IS NULL")
            qr.check("route_agency_required", "routes have no agency_id although the feed has several agencies",
                     "error", missing, file="routes.txt")
        else:
            qr.info("single_agency", "the feed contains a single agency", file="agency.txt", count=1)

    feeds = _scalar(conn, "SELECT COUNT(*) FROM feed_info")
    if feeds == 0:
        qr.info("feed_info_missing", "feed_info.txt is absent (optional): feed version and validity are unknown",
                file="feed_info.txt")
    else:
        if feeds > 1:
            qr.warn("feed_info_multiple_rows",
                    f"feed_info.txt has {feeds} rows; the GTFS specification allows exactly one. All rows are "
                    "stored; the first is used as the feed's identity.", file="feed_info.txt", count=feeds)
        bad = _scalar(conn, "SELECT COUNT(*) FROM feed_info WHERE feed_start_date > feed_end_date")
        qr.check("feed_info_date_order", "feed_info rows with feed_start_date after feed_end_date", "error", bad,
                 file="feed_info.txt")


# ---------------------------------------------------------------------------
# Stops, routes, trips
# ---------------------------------------------------------------------------

def check_network(conn: sqlite3.Connection, qr: QualityReport) -> None:
    missing_parent = _scalar(conn, "SELECT COUNT(*) FROM stops WHERE location_type IN (2, 3, 4) AND parent_station IS NULL")
    qr.check("stop_parent_required", "stops of location_type 2, 3 or 4 have no parent_station", "error",
             missing_parent, file="stops.txt")

    null_island = _scalar(conn, "SELECT COUNT(*) FROM stops WHERE stop_lat = 0 AND stop_lon = 0")
    qr.check("stop_at_null_island", "stops are located at coordinates (0, 0)", "warning", null_island, file="stops.txt")

    unused_where = ("FROM stops s WHERE (s.location_type IS NULL OR s.location_type = 0) AND NOT EXISTS "
                    "(SELECT 1 FROM stop_times t WHERE t.stop_id = s.stop_id)")
    unused = _scalar(conn, f"SELECT COUNT(*) {unused_where}")
    qr.check("unused_stops", "stops are never served by any stop_time", "warning", unused, file="stops.txt",
             examples=_examples(conn, f"SELECT s.stop_id {unused_where}") if unused else [])

    no_trips = ("FROM routes r WHERE NOT EXISTS (SELECT 1 FROM trips t WHERE t.route_id = r.route_id)")
    n = _scalar(conn, f"SELECT COUNT(*) {no_trips}")
    qr.check("routes_without_trips", "routes have no trips", "warning", n, file="routes.txt",
             examples=_examples(conn, f"SELECT r.route_id {no_trips}") if n else [])

    # Informational duplicate findings (legitimate in transit data; useful to know before transfer logic).
    dup_names = _scalar(conn, "SELECT COUNT(*) FROM (SELECT stop_name FROM stops WHERE stop_name IS NOT NULL "
                              "GROUP BY stop_name HAVING COUNT(*) > 1)")
    if dup_names:
        qr.info("duplicate_stop_names", f"{dup_names:,} stop name(s) are shared by more than one stop_id "
                "(normal for opposite-direction stops; routing must use stop_id, not names)", file="stops.txt",
                count=dup_names)
    dup_loc = _scalar(conn, "SELECT COUNT(*) FROM (SELECT 1 FROM stops WHERE stop_lat IS NOT NULL "
                            "GROUP BY stop_lat, stop_lon HAVING COUNT(*) > 1)")
    if dup_loc:
        qr.info("duplicate_stop_locations", f"{dup_loc:,} coordinate pair(s) are shared by more than one stop_id",
                file="stops.txt", count=dup_loc)


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------

def check_calendar(conn: sqlite3.Connection, qr: QualityReport) -> None:
    cal, dates = _scalar(conn, "SELECT COUNT(*) FROM calendar"), _scalar(conn, "SELECT COUNT(*) FROM calendar_dates")
    if cal == 0 and dates == 0:
        qr.error("no_service_calendar", "neither calendar.txt nor calendar_dates.txt contains any row")
        return
    if cal:
        span = conn.execute("SELECT MIN(start_date), MAX(end_date) FROM calendar").fetchone()
        qr.info("calendar_span", f"calendar.txt covers service dates {span[0]} to {span[1]} across {cal:,} service(s)",
                file="calendar.txt", count=cal)
        dead = ("FROM calendar c WHERE monday + tuesday + wednesday + thursday + friday + saturday + sunday = 0 "
                "AND NOT EXISTS (SELECT 1 FROM calendar_dates d WHERE d.service_id = c.service_id AND d.exception_type = 1)")
        n = _scalar(conn, f"SELECT COUNT(*) {dead}")
        qr.check("calendar_never_active", "calendar services run on no weekday and have no added dates", "warning", n,
                 file="calendar.txt", examples=_examples(conn, f"SELECT c.service_id {dead}") if n else [])
        unused = ("FROM calendar c WHERE NOT EXISTS (SELECT 1 FROM trips t WHERE t.service_id = c.service_id)")
        n = _scalar(conn, f"SELECT COUNT(*) {unused}")
        qr.check("calendar_unused_service", "calendar services are used by no trip", "info", n, file="calendar.txt",
                 examples=_examples(conn, f"SELECT c.service_id {unused}") if n else [])
    else:
        qr.info("calendar_absent", "calendar.txt is absent; service days are defined by calendar_dates.txt only",
                file="calendar_dates.txt")
    if dates:
        removal = ("FROM calendar_dates d WHERE d.exception_type = 2 AND NOT EXISTS "
                   "(SELECT 1 FROM calendar c WHERE c.service_id = d.service_id)")
        n = _scalar(conn, f"SELECT COUNT(*) {removal}")
        qr.check("calendar_removal_without_base", "calendar_dates removals reference a service that has no calendar row "
                 "(nothing to remove)", "warning", n, file="calendar_dates.txt",
                 examples=_examples(conn, f"SELECT DISTINCT d.service_id {removal}") if n else [])
        unused = ("FROM calendar_dates d WHERE NOT EXISTS (SELECT 1 FROM trips t WHERE t.service_id = d.service_id)")
        n = _scalar(conn, f"SELECT COUNT(DISTINCT d.service_id) {unused}")
        qr.check("calendar_dates_unused_service", "calendar_dates service_id(s) are used by no trip", "info", n,
                 file="calendar_dates.txt")
    else:
        qr.info("calendar_dates_absent", "calendar_dates.txt is absent or empty; there are no service exceptions",
                file="calendar_dates.txt")


# ---------------------------------------------------------------------------
# Stop times (the big table)
# ---------------------------------------------------------------------------

_SCHEDULE_CTE = """
WITH w AS (
    SELECT trip_id, stop_sequence, stop_id, arrival_time AS a, departure_time AS d, shape_dist_traveled AS sd,
           LAG(departure_time) OVER win AS prev_d, LAG(arrival_time) OVER win AS prev_a,
           LAG(shape_dist_traveled) OVER win AS prev_sd, LAG(stop_id) OVER win AS prev_stop
    FROM stop_times
    WINDOW win AS (PARTITION BY trip_id ORDER BY stop_sequence)
)
"""

# (code, description, severity, file, SQL predicate over the window CTE)
_SCHEDULE_RULES = (
    ("departure_before_arrival", "stop_times depart before they arrive", "error", "stop_times.txt",
     "a IS NOT NULL AND d IS NOT NULL AND d < a"),
    ("time_travel", "stop_times arrive before the previous stop's departure (time runs backwards along the trip)",
     "error", "stop_times.txt", "COALESCE(a, d) IS NOT NULL AND prev_d IS NOT NULL AND COALESCE(a, d) < prev_d"),
    ("stop_time_dist_decreasing", "stop_times have a shape_dist_traveled that decreases along the trip", "error",
     "stop_times.txt", "sd IS NOT NULL AND prev_sd IS NOT NULL AND sd < prev_sd"),
    ("consecutive_duplicate_stop", "stop_times serve the same stop as the previous stop_time of the trip", "warning",
     "stop_times.txt", "prev_stop IS NOT NULL AND stop_id = prev_stop"),
)


def check_stop_times(conn: sqlite3.Connection, qr: QualityReport) -> None:
    # One pass over stop_times in (trip_id, stop_sequence) order computes every rule at once.
    selects = ", ".join(f"COALESCE(SUM({pred}), 0)" for *_, pred in _SCHEDULE_RULES)
    totals = conn.execute(f"{_SCHEDULE_CTE} SELECT {selects} FROM w").fetchone()
    for (code, description, severity, file, pred), total in zip(_SCHEDULE_RULES, totals):
        examples: list[str] = []
        if total:
            rows = conn.execute(f"{_SCHEDULE_CTE} SELECT trip_id, stop_sequence FROM w WHERE {pred} LIMIT {SAMPLE_SIZE}")
            examples = [f"(trip_id={r[0]!r}, stop_sequence={r[1]})" for r in rows]
        qr.check(code, description, severity, int(total), file=file, examples=examples)

    edge = (
        "FROM (SELECT trip_id, MIN(stop_sequence) AS lo, MAX(stop_sequence) AS hi FROM stop_times GROUP BY trip_id) g "
        "JOIN stop_times s ON s.trip_id = g.trip_id AND s.stop_sequence IN (g.lo, g.hi) "
        "WHERE s.arrival_time IS NULL AND s.departure_time IS NULL"
    )
    n = _scalar(conn, f"SELECT COUNT(*) {edge}")
    qr.check("trip_edge_time_missing", "first/last stop_times of a trip have neither arrival_time nor departure_time",
             "error", n, file="stop_times.txt",
             examples=_examples(conn, f"SELECT s.trip_id {edge}") if n else [])

    # Phase 0 warning, same wording.
    short = _scalar(conn, "SELECT COUNT(*) FROM trips t WHERE t.trip_id NOT IN "
                          "(SELECT trip_id FROM stop_times GROUP BY trip_id HAVING COUNT(*) >= 2)")
    qr.check("trip_too_short", "trip(s) have fewer than 2 stop_times and can never produce a journey", "warning", short,
             file="trips.txt", message=f"{short:,} trip(s) have fewer than 2 stop_times and can never produce a journey")

    overnight = _scalar(conn, "SELECT COUNT(*) FROM stop_times WHERE arrival_time >= '24:00:00' OR departure_time >= '24:00:00'")
    if overnight:
        qr.info("overnight_service", f"{overnight:,} stop_time row(s) use hours of 24 or more (service continuing "
                "past midnight); they belong to the service day on which the trip starts", file="stop_times.txt",
                count=overnight)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def build_shapes_summary(conn: sqlite3.Connection) -> int:
    """Fill the derived ``shapes`` table from ``shape_points``. Returns the number of shapes."""
    conn.execute(
        "INSERT INTO shapes(shape_id, point_count, min_lat, min_lon, max_lat, max_lon, max_dist_traveled) "
        "SELECT shape_id, COUNT(*), MIN(shape_pt_lat), MIN(shape_pt_lon), MAX(shape_pt_lat), MAX(shape_pt_lon), "
        "MAX(shape_dist_traveled) FROM shape_points GROUP BY shape_id")
    return _scalar(conn, "SELECT COUNT(*) FROM shapes")


def check_shapes(conn: sqlite3.Connection, qr: QualityReport) -> None:
    n_shapes = _scalar(conn, "SELECT COUNT(*) FROM shapes")
    if n_shapes == 0:
        qr.info("shapes_absent", "shapes.txt is absent or empty; no route geometry is available. Map visualisation "
                "must fall back to stop-sequence polylines (clearly labelled as such).", file="shapes.txt")
        return
    short = _scalar(conn, "SELECT COUNT(*) FROM shapes WHERE point_count < 2")
    qr.check("shape_too_short", "shapes have fewer than 2 points", "warning", short, file="shapes.txt")

    window = ("WITH w AS (SELECT shape_id, shape_pt_sequence AS seq, shape_dist_traveled AS d, "
              "LAG(shape_dist_traveled) OVER (PARTITION BY shape_id ORDER BY shape_pt_sequence) AS prev_d "
              "FROM shape_points) ")
    n = _scalar(conn, f"{window} SELECT COUNT(*) FROM w WHERE d IS NOT NULL AND prev_d IS NOT NULL AND d < prev_d")
    qr.check("shape_point_dist_decreasing", "shape points have a shape_dist_traveled that decreases along the shape", "error",
             n, file="shapes.txt")

    unused = _scalar(conn, "SELECT COUNT(*) FROM shapes WHERE shape_id NOT IN "
                           "(SELECT DISTINCT shape_id FROM trips WHERE shape_id IS NOT NULL)")
    qr.check("unused_shapes", "shapes are referenced by no trip", "info", unused, file="shapes.txt")

    no_shape = _scalar(conn, "SELECT COUNT(*) FROM trips WHERE shape_id IS NULL")
    qr.check("trips_without_shape", "trips have no shape_id although shapes.txt exists (their geometry is unknown)",
             "warning", no_shape, file="trips.txt")


# ---------------------------------------------------------------------------
# Column usage and extensions
# ---------------------------------------------------------------------------

def column_usage(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Non-NULL count of every column of every GTFS table: shows which optional fields the feed really uses."""
    usage: dict[str, dict[str, int]] = {}
    for spec in TABLE_SPECS:
        cols = spec.column_names
        row = conn.execute(f"SELECT COUNT(*), {', '.join(f'COUNT({c})' for c in cols)} FROM {spec.table}").fetchone()
        if row[0]:
            usage[spec.table] = {c: int(n) for c, n in zip(cols, row[1:])}
    return usage


def describe_extensions(usage: dict[str, dict[str, int]], column_report: dict[str, dict[str, list[str]]],
                        qr: QualityReport) -> None:
    for filename, cols in column_report.items():
        spec = next(s for s in TABLE_SPECS if s.filename == filename)
        for col in cols["extension_stored"]:
            used = usage.get(spec.table, {}).get(col, 0)
            total = _scalar_rows(usage, spec.table)
            if used:
                qr.info("extension_column_stored", f"{filename}: '{col}' is not a GTFS-standard column; it is stored "
                        f"as-is ({used:,} of {total:,} rows populated)", file=filename, count=used)
            else:
                qr.info("extension_column_empty", f"{filename}: '{col}' is not a GTFS-standard column and is empty in "
                        "every row", file=filename, count=0)
        if cols["unsupported"]:
            qr.warn("unsupported_columns", f"{filename}: column(s) {', '.join(cols['unsupported'])} are present but are "
                    "not stored by this importer", file=filename, count=len(cols["unsupported"]))


def _scalar_rows(usage: dict[str, dict[str, int]], table: str) -> int:
    first = SPEC_BY_TABLE[table].columns[0].name
    return usage.get(table, {}).get(first, 0)


def run_integrity_checks(conn: sqlite3.Connection, qr: QualityReport) -> None:
    """All set-based checks that need indexes in place. Call after the unique indexes exist."""
    check_references(conn, qr)
    check_agency_and_feed(conn, qr)
    check_network(conn, qr)
    check_calendar(conn, qr)
    check_stop_times(conn, qr)
    check_shapes(conn, qr)
