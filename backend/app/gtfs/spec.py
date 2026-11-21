"""Declarative description of every GTFS Schedule file the importer understands.

One :class:`TableSpec` per file. The loader builds its row parsers from these
specs, the archive inspector builds its header checks from them, and a unit test
asserts that every column listed here exists in the SQLite DDL (and vice versa),
so the three can never silently drift apart.

Column ``kind`` values
----------------------
``text``      free text, stripped, empty -> NULL
``id``        identifier; kept as a *string* (never converted to a number)
``url`` / ``email`` / ``lang`` / ``color`` / ``currency`` / ``tz``   validated text
``int``       integer, optionally bounded (``lo``/``hi``)
``float``     finite number, optionally bounded
``lat`` / ``lon``   WGS84 coordinates, stored as REAL (IEEE double: ~15 significant digits are preserved)
``enum``      integer chosen from ``allowed``
``date``      ``YYYYMMDD``, must be a real calendar date; stored as the 8-digit string
``time``      GTFS time ``H:MM:SS`` / ``HH:MM:SS``; hours may exceed 23. Stored zero-padded so that
              string order equals chronological order

``required``  = GTFS "Required": the column must exist in the header and be non-empty in every row.
Conditionally required fields are optional here and enforced by the table's row hook or by
set-based SQL checks in :mod:`app.gtfs.validation`.

Official reference: https://gtfs.org/documentation/schedule/reference/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class Col:
    name: str
    kind: str = "text"
    required: bool = False
    lo: Optional[float] = None
    hi: Optional[float] = None
    allowed: tuple[int, ...] = ()
    blank_ok: bool = False  # header must carry the column, but individual rows may leave it empty
    extension: bool = False  # not part of the GTFS specification, but stored because the real feed uses it


@dataclass(frozen=True)
class TableSpec:
    table: str  # SQLite table the rows are loaded into
    filename: str
    columns: tuple[Col, ...]
    key: tuple[str, ...] = ()  # natural key; duplicates are fatal
    key_in_memory: bool = True  # False for huge tables: duplicates are found with set-based SQL afterwards
    required_file: bool = False
    needs_one_of: tuple[str, ...] = ()  # header must contain at least one of these columns
    also_header: tuple[str, ...] = ()  # columns GTFS marks "conditionally required" that this importer insists on in the header

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Columns that must be present in the header."""
        return tuple(dict.fromkeys((*(c.name for c in self.columns if c.required), *self.also_header)))

    @property
    def standard_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if not c.extension)

    @property
    def extension_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.extension)


def _c(name: str, kind: str = "text", required: bool = False, **kw) -> Col:
    return Col(name, kind, required, **kw)


def _enum(name: str, allowed: tuple[int, ...], required: bool = False) -> Col:
    return Col(name, "enum", required, allowed=allowed)


AGENCY = TableSpec(
    "agency", "agency.txt",
    (
        _c("agency_id", "id"),  # conditionally required (required when the feed has several agencies)
        _c("agency_name", required=True), _c("agency_url", "url", True), _c("agency_timezone", "tz", True),
        _c("agency_lang", "lang"), _c("agency_phone"), _c("agency_fare_url", "url"), _c("agency_email", "email"),
    ),
    key=("agency_id",),
)

STOPS = TableSpec(
    "stops", "stops.txt",
    (
        _c("stop_id", "id", True), _c("stop_code"),
        _c("stop_name"),  # conditionally required: location_type 0, 1, 2 (enforced by the row hook)
        _c("tts_stop_name"), _c("stop_desc"),
        _c("stop_lat", "lat"), _c("stop_lon", "lon"),  # conditionally required: location_type 0, 1, 2
        _c("zone_id", "id"), _c("stop_url", "url"),
        _enum("location_type", (0, 1, 2, 3, 4)), _c("parent_station", "id"),
        _c("stop_timezone", "tz"), _enum("wheelchair_boarding", (0, 1, 2)),
        _c("level_id", "id"), _c("platform_code"),
    ),
    key=("stop_id",), required_file=True, also_header=("stop_name", "stop_lat", "stop_lon"),
)

ROUTES = TableSpec(
    "routes", "routes.txt",
    (
        _c("route_id", "id", True), _c("agency_id", "id"),
        _c("route_short_name"), _c("route_long_name"), _c("route_desc"),
        Col("route_type", "int", True, lo=0, hi=9999),  # basic 0-12 plus the extended 100-1799 codes
        _c("route_url", "url"), _c("route_color", "color"), _c("route_text_color", "color"),
        Col("route_sort_order", "int", lo=0), _enum("continuous_pickup", (0, 1, 2, 3)),
        _enum("continuous_drop_off", (0, 1, 2, 3)), _c("network_id", "id"),
    ),
    key=("route_id",), required_file=True, needs_one_of=("route_short_name", "route_long_name"),
)

TRIPS = TableSpec(
    "trips", "trips.txt",
    (
        _c("trip_id", "id", True), _c("route_id", "id", True), _c("service_id", "id", True),
        _c("trip_headsign"), _c("trip_short_name"), _enum("direction_id", (0, 1)), _c("block_id", "id"),
        _c("shape_id", "id"), _enum("wheelchair_accessible", (0, 1, 2)), _enum("bikes_allowed", (0, 1, 2)),
    ),
    key=("trip_id",), required_file=True,
)

STOP_TIMES = TableSpec(
    "stop_times", "stop_times.txt",
    (
        _c("trip_id", "id", True),
        # GTFS: conditionally required (empty is legal for non-timepoint stops); the header must carry the columns
        Col("arrival_time", "time", True, blank_ok=True), Col("departure_time", "time", True, blank_ok=True),
        _c("stop_id", "id", True),
        Col("stop_sequence", "int", True, lo=0),
        _c("stop_headsign"), _enum("pickup_type", (0, 1, 2, 3)), _enum("drop_off_type", (0, 1, 2, 3)),
        _enum("continuous_pickup", (0, 1, 2, 3)), _enum("continuous_drop_off", (0, 1, 2, 3)),
        Col("shape_dist_traveled", "float", lo=0), _enum("timepoint", (0, 1)),
        # --- extensions found in the Delhi feed (not GTFS-standard) ---
        Col("fare_stage", "int", lo=0, extension=True), Col("stop_dist", "float", lo=0, extension=True),
    ),
    key=("trip_id", "stop_sequence"), key_in_memory=False, required_file=True,
)

CALENDAR = TableSpec(
    "calendar", "calendar.txt",
    (
        _c("service_id", "id", True),
        *(Col(day, "enum", True, allowed=(0, 1)) for day in WEEKDAYS),
        _c("start_date", "date", True), _c("end_date", "date", True),
    ),
    key=("service_id",),
)

CALENDAR_DATES = TableSpec(
    "calendar_dates", "calendar_dates.txt",
    (_c("service_id", "id", True), _c("date", "date", True), _enum("exception_type", (1, 2), True)),
    key=("service_id", "date"),
)

SHAPE_POINTS = TableSpec(
    "shape_points", "shapes.txt",
    (
        _c("shape_id", "id", True), Col("shape_pt_lat", "lat", True), Col("shape_pt_lon", "lon", True),
        Col("shape_pt_sequence", "int", True, lo=0), Col("shape_dist_traveled", "float", lo=0),
    ),
    key=("shape_id", "shape_pt_sequence"), key_in_memory=False,
)

FEED_INFO = TableSpec(
    "feed_info", "feed_info.txt",
    (
        _c("feed_publisher_name", required=True), _c("feed_publisher_url", "url", True), _c("feed_lang", "lang", True),
        _c("default_lang", "lang"), _c("feed_start_date", "date"), _c("feed_end_date", "date"),
        _c("feed_version"), _c("feed_contact_email", "email"), _c("feed_contact_url", "url"),
    ),
)

FREQUENCIES = TableSpec(
    "frequencies", "frequencies.txt",
    (
        _c("trip_id", "id", True), _c("start_time", "time", True), _c("end_time", "time", True),
        Col("headway_secs", "int", True, lo=1), _enum("exact_times", (0, 1)),
    ),
    key=("trip_id", "start_time"),
)

TRANSFERS = TableSpec(
    "transfers", "transfers.txt",
    (
        _c("from_stop_id", "id"), _c("to_stop_id", "id"), _c("from_route_id", "id"), _c("to_route_id", "id"),
        _c("from_trip_id", "id"), _c("to_trip_id", "id"), _enum("transfer_type", (0, 1, 2, 3, 4, 5), True),
        Col("min_transfer_time", "int", lo=0),
    ),
)

LEVELS = TableSpec(
    "levels", "levels.txt",
    (_c("level_id", "id", True), Col("level_index", "float", True), _c("level_name")),
    key=("level_id",),
)

PATHWAYS = TableSpec(
    "pathways", "pathways.txt",
    (
        _c("pathway_id", "id", True), _c("from_stop_id", "id", True), _c("to_stop_id", "id", True),
        _enum("pathway_mode", (1, 2, 3, 4, 5, 6, 7), True), _enum("is_bidirectional", (0, 1), True),
        Col("length", "float", lo=0), Col("traversal_time", "int", lo=1), Col("stair_count", "int"),
        Col("max_slope", "float"), Col("min_width", "float", lo=0),
        _c("signposted_as"), _c("reversed_signposted_as"),
    ),
    key=("pathway_id",),
)

ATTRIBUTIONS = TableSpec(
    "attributions", "attributions.txt",
    (
        _c("attribution_id", "id"), _c("agency_id", "id"), _c("route_id", "id"), _c("trip_id", "id"),
        _c("organization_name", required=True), _enum("is_producer", (0, 1)), _enum("is_operator", (0, 1)),
        _enum("is_authority", (0, 1)), _c("attribution_url", "url"), _c("attribution_email", "email"),
        _c("attribution_phone"),
    ),
    key=("attribution_id",),
)

FARE_ATTRIBUTES = TableSpec(
    "fare_attributes", "fare_attributes.txt",
    (
        _c("fare_id", "id", True), Col("price", "float", True, lo=0), _c("currency_type", "currency", True),
        _enum("payment_method", (0, 1), True),
        # empty means "unlimited transfers" and is therefore preserved as NULL
        _enum("transfers", (0, 1, 2)), _c("agency_id", "id"), Col("transfer_duration", "int", lo=0),
    ),
    key=("fare_id",),
)

FARE_RULES = TableSpec(
    "fare_rules", "fare_rules.txt",
    (_c("fare_id", "id", True), _c("route_id", "id"), _c("origin_id", "id"), _c("destination_id", "id"),
     _c("contains_id", "id")),
)

# Order matters: it is the load order (parents before children keeps error reports readable).
TABLE_SPECS: tuple[TableSpec, ...] = (
    AGENCY, STOPS, ROUTES, LEVELS, TRIPS, CALENDAR, CALENDAR_DATES, SHAPE_POINTS, STOP_TIMES, FREQUENCIES, TRANSFERS,
    PATHWAYS, ATTRIBUTIONS, FARE_ATTRIBUTES, FARE_RULES, FEED_INFO,
)
SPEC_BY_TABLE = {s.table: s for s in TABLE_SPECS}
SPEC_BY_FILE = {s.filename: s for s in TABLE_SPECS}

# GTFS-defined files that are valid but intentionally *not* imported by this phase.
RECOGNISED_UNIMPORTED_FILES = (
    "translations.txt", "timeframes.txt", "rider_categories.txt", "fare_media.txt", "fare_products.txt",
    "fare_leg_rules.txt", "fare_leg_join_rules.txt", "fare_transfer_rules.txt", "areas.txt", "stop_areas.txt",
    "networks.txt", "route_networks.txt", "location_groups.txt", "location_group_stops.txt", "locations.geojson",
    "booking_rules.txt",
)

# Footprint of the "required" tables for archive discovery (kept for Phase 0 compatibility).
REQUIRED_SPECS = tuple(s for s in TABLE_SPECS if s.required_file)
SERVICE_SPECS = (CALENDAR, CALENDAR_DATES)


@dataclass(frozen=True)
class Reference:
    """A foreign-key style relationship verified with set-based SQL after loading."""

    child: str
    child_column: str
    parent: str
    parent_column: str
    description: str
    severity: str = "error"
    code: str = ""
    parent_optional: bool = False  # skip the check (and say so) when the parent file is absent/empty


REFERENCES: tuple[Reference, ...] = (
    Reference("trips", "route_id", "routes", "route_id", "trips reference a route_id missing from routes.txt", code="trip_route_missing"),
    Reference("trips", "shape_id", "shapes", "shape_id",
              "trips reference a shape_id missing from shapes.txt", code="trip_shape_missing"),
    Reference("stop_times", "trip_id", "trips", "trip_id", "stop_times rows reference a trip_id missing from trips.txt", code="stop_time_trip_missing"),
    Reference("stop_times", "stop_id", "stops", "stop_id", "stop_times rows reference a stop_id missing from stops.txt", code="stop_time_stop_missing"),
    Reference("routes", "agency_id", "agency", "agency_id", "routes reference an agency_id missing from agency.txt", code="route_agency_missing", parent_optional=True),
    Reference("stops", "parent_station", "stops", "stop_id", "stops reference a parent_station that is not in stops.txt", code="stop_parent_missing"),
    Reference("stops", "level_id", "levels", "level_id", "stops reference a level_id missing from levels.txt", code="stop_level_missing"),
    Reference("frequencies", "trip_id", "trips", "trip_id", "frequencies reference a trip_id missing from trips.txt", code="frequency_trip_missing"),
    Reference("transfers", "from_stop_id", "stops", "stop_id", "transfers reference a from_stop_id missing from stops.txt", code="transfer_from_stop_missing"),
    Reference("transfers", "to_stop_id", "stops", "stop_id", "transfers reference a to_stop_id missing from stops.txt", code="transfer_to_stop_missing"),
    Reference("transfers", "from_route_id", "routes", "route_id", "transfers reference a from_route_id missing from routes.txt", code="transfer_from_route_missing"),
    Reference("transfers", "to_route_id", "routes", "route_id", "transfers reference a to_route_id missing from routes.txt", code="transfer_to_route_missing"),
    Reference("transfers", "from_trip_id", "trips", "trip_id", "transfers reference a from_trip_id missing from trips.txt", code="transfer_from_trip_missing"),
    Reference("transfers", "to_trip_id", "trips", "trip_id", "transfers reference a to_trip_id missing from trips.txt", code="transfer_to_trip_missing"),
    Reference("pathways", "from_stop_id", "stops", "stop_id", "pathways reference a from_stop_id missing from stops.txt", code="pathway_from_stop_missing"),
    Reference("pathways", "to_stop_id", "stops", "stop_id", "pathways reference a to_stop_id missing from stops.txt", code="pathway_to_stop_missing"),
    Reference("attributions", "agency_id", "agency", "agency_id", "attributions reference an agency_id missing from agency.txt", code="attribution_agency_missing", parent_optional=True),
    Reference("attributions", "route_id", "routes", "route_id", "attributions reference a route_id missing from routes.txt", code="attribution_route_missing"),
    Reference("attributions", "trip_id", "trips", "trip_id", "attributions reference a trip_id missing from trips.txt", code="attribution_trip_missing"),
    Reference("fare_rules", "fare_id", "fare_attributes", "fare_id", "fare_rules reference a fare_id missing from fare_attributes.txt", code="fare_rule_fare_missing"),
    Reference("fare_rules", "route_id", "routes", "route_id", "fare_rules reference a route_id missing from routes.txt", code="fare_rule_route_missing"),
    Reference("fare_attributes", "agency_id", "agency", "agency_id", "fare_attributes reference an agency_id missing from agency.txt", code="fare_agency_missing", parent_optional=True),
)
