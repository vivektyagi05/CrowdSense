"""Streaming, strictly validated GTFS -> SQLite loader (table-driven).

Policy: **no malformed record is ever silently discarded.** Each bad row becomes
an error record (file, line number, reason). The import is aborted once loading
finishes (or earlier, if errors exceed ``MAX_ERRORS``), so a feed with bad rows
never produces a database.

Memory: rows are streamed from the ZIP and inserted in batches. Only the key sets of
the small/medium tables (stops, routes, trips, calendar ...) are kept in memory for
duplicate detection; ``stop_times`` and ``shape_points`` (millions of rows) are never
held in memory - their duplicates are found afterwards with set-based SQL.

Parsers are generated from :mod:`app.gtfs.spec`; this module contains no per-file
column lists, so adding a column means editing the spec and the DDL only.
"""

from __future__ import annotations

import csv
import logging
import math
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Sequence
from urllib.parse import urlsplit

from app.gtfs.archive import GtfsArchive, iter_rows
from app.gtfs.errors import GtfsDataError
from app.gtfs.spec import SPEC_BY_TABLE, TABLE_SPECS, Col, TableSpec

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50_000
MAX_ERROR_SAMPLES = 50  # detailed records kept per import
MAX_ERRORS = 1_000  # abort loading once this many bad rows were seen

_TIME_RE = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHASE = "data_validation"


class RowError(ValueError):
    """A single row failed validation."""


class ErrorCollector:
    """Counts every error but keeps only a bounded sample of details."""

    def __init__(self, max_samples: int = MAX_ERROR_SAMPLES, max_errors: int = MAX_ERRORS) -> None:
        self.max_samples = max_samples
        self.max_errors = max_errors
        self.total = 0
        self.samples: list[dict[str, object]] = []

    def add(self, file: str, line: int | None, message: str) -> None:
        self.total += 1
        if len(self.samples) < self.max_samples:
            self.samples.append({"file": file, "line": line, "message": message})

    def __bool__(self) -> bool:
        return self.total > 0


@dataclass
class LoadStats:
    """Row accounting for one file. ``rows_read = rows_imported + rows_rejected`` on every finished load."""

    rows_read: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0


# ---------------------------------------------------------------------------
# Value parsers (operate on a stripped, non-empty string)
# ---------------------------------------------------------------------------

def normalise_time(value: str, name: str) -> str | None:
    """Validate ``H:MM:SS``/``HH:MM:SS`` (hours may exceed 23) and zero-pad hours.

    Zero-padding makes lexicographic order equal chronological order, which the
    journey query relies on. For the Delhi feed this is the identity transform.
    """
    value = value.strip()
    if not value:
        return None
    match = _TIME_RE.match(value)
    if not match:
        raise RowError(f"{name} {value!r} is not a valid GTFS time (H:MM:SS)")
    if len(value) == 8:
        return value
    return f"{int(match.group(1)):02d}:{match.group(2)}:{match.group(3)}"


def _check_date(value: str, name: str) -> str:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise RowError(f"{name} {value!r} must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        raise RowError(f"{name} {value!r} is not a real calendar date") from None
    return value


def _inner_parser(col: Col) -> Optional[Callable[[str], object]]:
    """Return the validating converter for ``col.kind`` (``None`` = keep the stripped string)."""
    name, kind = col.name, col.kind
    if kind in ("text", "id"):
        return None
    if kind == "url":
        def parse_url(v: str) -> str:
            parts = urlsplit(v)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise RowError(f"{name} {v!r} is not a valid http(s) URL")
            return v
        return parse_url
    if kind == "email":
        def parse_email(v: str) -> str:
            if not _EMAIL_RE.match(v):
                raise RowError(f"{name} {v!r} is not a valid email address")
            return v
        return parse_email
    if kind == "lang":
        def parse_lang(v: str) -> str:
            if not _LANG_RE.match(v):
                raise RowError(f"{name} {v!r} is not a valid language code")
            return v
        return parse_lang
    if kind == "color":
        def parse_color(v: str) -> str:
            if not _COLOR_RE.match(v):
                raise RowError(f"{name} {v!r} must be a 6-digit hexadecimal colour")
            return v
        return parse_color
    if kind == "currency":
        def parse_currency(v: str) -> str:
            if not _CURRENCY_RE.match(v):
                raise RowError(f"{name} {v!r} must be a 3-letter ISO 4217 currency code")
            return v.upper()
        return parse_currency
    if kind == "tz":
        def parse_tz(v: str) -> str:
            if " " in v:
                raise RowError(f"{name} {v!r} is not a valid timezone name")
            return v
        return parse_tz
    if kind == "int":
        lo, hi = col.lo, col.hi
        def parse_int(v: str) -> int:
            digits = v[1:] if v[:1] in "+-" else v
            if not (digits.isascii() and digits.isdigit()):
                raise RowError(f"{name} {v!r} is not an integer")
            number = int(v)
            if lo is not None and number < lo:
                raise RowError(f"{name} {v!r} must be >= {int(lo)}")
            if hi is not None and number > hi:
                raise RowError(f"{name} {v!r} must be <= {int(hi)}")
            return number
        return parse_int
    if kind in ("float", "lat", "lon"):
        lo, hi = (-90.0, 90.0) if kind == "lat" else (-180.0, 180.0) if kind == "lon" else (col.lo, col.hi)
        def parse_float(v: str) -> float:
            try:
                number = float(v)
            except ValueError:
                raise RowError(f"{name} {v!r} is not a number") from None
            if not math.isfinite(number):
                raise RowError(f"{name} {v!r} is not a finite number")
            if (lo is not None and number < lo) or (hi is not None and number > hi):
                low = "-inf" if lo is None else lo
                high = "inf" if hi is None else hi
                raise RowError(f"{name} {v!r} is outside [{low}, {high}]")
            return number
        return parse_float
    if kind == "enum":
        allowed = col.allowed
        def parse_enum(v: str) -> int:
            if not (v.isascii() and v.isdigit()) or int(v) not in allowed:
                raise RowError(f"{name} {v!r} must be one of {', '.join(map(str, allowed))}")
            return int(v)
        return parse_enum
    if kind == "date":
        return lambda v: _check_date(v, name)
    if kind == "time":
        return lambda v: normalise_time(v, name)
    raise ValueError(f"unknown column kind {kind!r} for {col.name}")


def make_converter(col: Col) -> Callable[[str], object]:
    """Build the raw-cell -> typed-value function for one column."""
    inner = _inner_parser(col)
    name = col.name
    if col.required and not col.blank_ok:
        if inner is None:
            def convert(raw: str) -> object:
                value = raw.strip()
                if not value:
                    raise RowError(f"{name} is empty")
                return value
        else:
            def convert(raw: str) -> object:
                value = raw.strip()
                if not value:
                    raise RowError(f"{name} is empty")
                return inner(value)
    elif inner is None:
        def convert(raw: str) -> object:
            return raw.strip() or None
    else:
        def convert(raw: str) -> object:
            value = raw.strip()
            return inner(value) if value else None
    return convert


# ---------------------------------------------------------------------------
# Row hooks: rules that involve several columns of one row
# ---------------------------------------------------------------------------

Hook = Callable[[list], None]


def _hook_for(spec: TableSpec) -> Optional[Callable[[dict[str, int]], Hook]]:
    return _HOOK_FACTORIES.get(spec.table)


def _agency_hook(ix: dict[str, int]) -> Hook:
    i = ix["agency_id"]

    def hook(out: list) -> None:
        if out[i] is None:
            out[i] = ""  # single-agency feed without agency_id (see schema docs)
    return hook


def _stops_hook(ix: dict[str, int]) -> Hook:
    loc, name, lat, lon = ix["location_type"], ix["stop_name"], ix["stop_lat"], ix["stop_lon"]

    def hook(out: list) -> None:
        located = out[loc] in (None, 0, 1, 2)  # GTFS: nodes/boarding areas may omit name and coordinates
        if located and out[name] is None:
            raise RowError("stop_name is empty")
        if located:
            if out[lat] is None:
                raise RowError("stop_lat is empty")
            if out[lon] is None:
                raise RowError("stop_lon is empty")
        elif (out[lat] is None) != (out[lon] is None):
            raise RowError("stop_lat and stop_lon must be given together")
    return hook


def _routes_hook(ix: dict[str, int]) -> Hook:
    short, long_ = ix["route_short_name"], ix["route_long_name"]

    def hook(out: list) -> None:
        if out[short] is None and out[long_] is None:
            raise RowError("route has neither route_short_name nor route_long_name")
    return hook


def _calendar_hook(ix: dict[str, int]) -> Hook:
    start, end = ix["start_date"], ix["end_date"]

    def hook(out: list) -> None:
        if out[start] > out[end]:
            raise RowError(f"start_date {out[start]} is after end_date {out[end]}")
    return hook


def _frequencies_hook(ix: dict[str, int]) -> Hook:
    start, end = ix["start_time"], ix["end_time"]

    def hook(out: list) -> None:
        if out[end] <= out[start]:
            raise RowError(f"end_time {out[end]} must be after start_time {out[start]}")
    return hook


def _transfers_hook(ix: dict[str, int]) -> Hook:
    kind = ix["transfer_type"]
    from_stop, to_stop, from_trip, to_trip = ix["from_stop_id"], ix["to_stop_id"], ix["from_trip_id"], ix["to_trip_id"]

    def hook(out: list) -> None:
        if out[kind] in (1, 2, 3):
            if out[from_stop] is None or out[to_stop] is None:
                raise RowError("from_stop_id and to_stop_id are required for transfer_type 1, 2 and 3")
        elif out[kind] in (4, 5) and (out[from_trip] is None or out[to_trip] is None):
            raise RowError("from_trip_id and to_trip_id are required for transfer_type 4 and 5")
    return hook


def _attributions_hook(ix: dict[str, int]) -> Hook:
    roles = [ix["is_producer"], ix["is_operator"], ix["is_authority"]]
    scopes = [ix["agency_id"], ix["route_id"], ix["trip_id"]]

    def hook(out: list) -> None:
        if not any(out[i] == 1 for i in roles):
            raise RowError("at least one of is_producer, is_operator, is_authority must be 1")
        if sum(out[i] is not None for i in scopes) > 1:
            raise RowError("only one of agency_id, route_id, trip_id may be set")
    return hook


_HOOK_FACTORIES: dict[str, Callable[[dict[str, int]], Hook]] = {
    "agency": _agency_hook, "stops": _stops_hook, "routes": _routes_hook, "calendar": _calendar_hook,
    "frequencies": _frequencies_hook, "transfers": _transfers_hook, "attributions": _attributions_hook,
}


# ---------------------------------------------------------------------------
# Parser factory
# ---------------------------------------------------------------------------

Parser = Callable[[Sequence[str]], tuple]


def make_parser(spec: TableSpec, header: Sequence[str]) -> Parser:
    """Build ``row -> tuple`` for ``spec`` given the actual header of the file.

    The tuple always has one slot per spec column, in spec order; columns missing from the
    header are NULL. Raises :class:`RowError` for any invalid value.
    """
    pos = {name: i for i, name in enumerate(header)}
    out_ix = {c.name: j for j, c in enumerate(spec.columns)}
    template: list = [None] * len(spec.columns)
    steps = [(pos[c.name], out_ix[c.name], make_converter(c)) for c in spec.columns if c.name in pos]
    hook_factory = _hook_for(spec)
    hook = hook_factory(out_ix) if hook_factory else None
    key_ix = [out_ix[k] for k in spec.key] if spec.key and spec.key_in_memory else []
    seen: set = set()

    def parse(row: Sequence[str]) -> tuple:
        out = template[:]
        for i, j, convert in steps:
            out[j] = convert(row[i])
        if hook is not None:
            hook(out)
        if key_ix:
            key = out[key_ix[0]] if len(key_ix) == 1 else tuple(out[j] for j in key_ix)
            if key in seen:
                label = spec.key[0] if len(spec.key) == 1 else "(" + ", ".join(spec.key) + ")"
                raise RowError(f"duplicate {label} {key!r}")
            seen.add(key)
        return tuple(out)

    return parse


# ---------------------------------------------------------------------------
# Table loader
# ---------------------------------------------------------------------------

def insert_sql(spec: TableSpec) -> str:
    columns = spec.column_names
    return f"INSERT INTO {spec.table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"


def load_table(
    conn: sqlite3.Connection,
    zf: zipfile.ZipFile,
    archive: GtfsArchive,
    table: str,
    errors: ErrorCollector,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> LoadStats:
    """Load one GTFS file into ``table`` and return its row accounting."""
    spec = SPEC_BY_TABLE[table]
    member = archive.members[spec.filename]
    header = archive.headers[spec.filename]
    parse = make_parser(spec, header)
    width = len(header)
    sql = insert_sql(spec)

    stats = LoadStats()
    batch: list[tuple] = []
    try:
        for line_no, row in iter_rows(zf, member):
            stats.rows_read += 1
            if len(row) != width:
                stats.rows_rejected += 1
                errors.add(spec.filename, line_no, f"expected {width} columns, found {len(row)}")
            else:
                try:
                    batch.append(parse(row))
                except RowError as exc:
                    stats.rows_rejected += 1
                    errors.add(spec.filename, line_no, str(exc))
            if errors.total >= errors.max_errors:
                raise GtfsDataError(
                    f"Aborted: {errors.total} invalid rows seen while reading {spec.filename}; fix the feed first",
                    phase=_PHASE, errors=list(errors.samples), total_errors=errors.total)
            if len(batch) >= batch_size:
                conn.executemany(sql, batch)
                stats.rows_imported += len(batch)
                batch.clear()
        if batch:
            conn.executemany(sql, batch)
            stats.rows_imported += len(batch)
    except UnicodeDecodeError as exc:
        raise GtfsDataError(f"{spec.filename} is not valid UTF-8 ({exc.reason})", phase=_PHASE,
                            errors=[{"file": spec.filename, "line": None, "message": "invalid UTF-8"}]) from exc
    except (zipfile.BadZipFile, csv.Error) as exc:
        raise GtfsDataError(f"{spec.filename} could not be read: {exc}", phase=_PHASE,
                            errors=[{"file": spec.filename, "line": None, "message": str(exc)}]) from exc
    logger.info("Loaded %s: %s rows from %s (%s rejected)", table, f"{stats.rows_imported:,}", spec.filename,
                f"{stats.rows_rejected:,}")
    return stats


# Order in which tables are loaded (parents first so error reports read naturally).
LOAD_ORDER = tuple(spec.table for spec in TABLE_SPECS)
TABLE_FILENAMES = {spec.table: spec.filename for spec in TABLE_SPECS}
