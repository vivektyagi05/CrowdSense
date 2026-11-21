"""SQLite schema (version 2) for the static GTFS feed.

Compatibility with schema version 1 (Phase 0)
---------------------------------------------
Every table and column created by Phase 0 still exists under the same name, so the
Phase 0 queries (stop search, direct journeys, health) run unchanged against a
version-2 database. Differences are additive, except for deliberate type changes in a
freshly built database: GTFS *enumerations* (``route_type``, ``location_type``,
``direction_id``, ``pickup_type``, ``drop_off_type``) are now ``INTEGER`` instead of
``TEXT`` digits, because they are numbers in the GTFS specification. Identifiers
(``*_id``) remain TEXT and are never converted.

What is new in version 2
------------------------
* ``agency``, ``shapes``, ``shape_points``, ``feed_info`` plus the optional GTFS tables
  ``frequencies, transfers, levels, pathways, attributions, fare_attributes, fare_rules``.
* All remaining standard optional columns of the Phase 0 tables (``stop_code``,
  ``route_desc``, ``block_id``, ``timepoint``, ``shape_dist_traveled`` ...).
* Two columns that are **not** part of the GTFS specification but are present in the Delhi
  feed's ``stop_times.txt``: ``fare_stage`` and ``stop_dist``. They are stored, not dropped,
  and reported as extensions in the import report.
* ``shapes`` is a *derived summary* (point count + bounding box per shape_id) computed from
  ``shape_points`` during import. It exists so ``trips.shape_id`` can reference something
  and so shape metadata can be read without touching 765k point rows.

Design notes
------------
* ``service_id`` cannot be a foreign key: GTFS allows it to be defined in ``calendar`` *or*
  ``calendar_dates``. It is verified set-based after the load instead.
* Foreign keys are declared (documentation + enforcement for any future writer) but the
  bulk load runs with ``foreign_keys=OFF`` and verifies them set-based afterwards, which
  produces far better error reports than failing on the first bad row.
* ``agency_id = ''`` stores the single agency of a feed that omits ``agency_id`` (GTFS allows
  this when there is exactly one agency). Routes without an ``agency_id`` then belong to it.
* Times stay ``HH:MM:SS`` text with zero-padded hours (hours may exceed 23), so string order
  equals chronological order.

Index review: see ``docs/PERFORMANCE.md`` (measured on the real 2.4M-row feed). In short:
``idx_stoptimes_stop`` became ``idx_stoptimes_stop_dep (stop_id, departure_time)`` - it still serves every
``stop_id`` lookup (leftmost prefix) and additionally turns time-ordered departures at a stop into a range scan.
"""

from __future__ import annotations

from app.gtfs.spec import TABLE_SPECS, WEEKDAYS  # noqa: F401  (WEEKDAYS re-exported for Phase 0 importers)

SCHEMA_VERSION = 2

# Phase 0 groupings. ``counts`` in health/import reports keep exactly these six tables
# so that Phase 0 clients and tests continue to work.
CORE_TABLES = ("stops", "routes", "trips", "stop_times")
SERVICE_TABLES = ("calendar", "calendar_dates")
ALL_TABLES = CORE_TABLES + SERVICE_TABLES

# Every table holding GTFS data (Phase 1). ``shapes`` is derived from ``shape_points``.
GTFS_TABLES = (
    "agency", "stops", "levels", "routes", "trips", "calendar", "calendar_dates", "shapes", "shape_points",
    "stop_times", "frequencies", "transfers", "pathways", "attributions", "fare_attributes", "fare_rules",
    "feed_info",
)

TABLES_DDL = """
CREATE TABLE agency(
    agency_id        TEXT NOT NULL PRIMARY KEY,
    agency_name      TEXT NOT NULL,
    agency_url       TEXT NOT NULL,
    agency_timezone  TEXT NOT NULL,
    agency_lang      TEXT,
    agency_phone     TEXT,
    agency_fare_url  TEXT,
    agency_email     TEXT
);

CREATE TABLE levels(
    level_id     TEXT PRIMARY KEY,
    level_index  REAL NOT NULL,
    level_name   TEXT
);

CREATE TABLE stops(
    stop_id              TEXT PRIMARY KEY,
    stop_name            TEXT,
    stop_lat             REAL,
    stop_lon             REAL,
    location_type        INTEGER,
    stop_code            TEXT,
    tts_stop_name        TEXT,
    stop_desc            TEXT,
    zone_id              TEXT,
    stop_url             TEXT,
    parent_station       TEXT REFERENCES stops(stop_id),
    stop_timezone        TEXT,
    wheelchair_boarding  INTEGER,
    level_id             TEXT,
    platform_code        TEXT
);

CREATE TABLE routes(
    route_id             TEXT PRIMARY KEY,
    agency_id            TEXT,
    route_short_name     TEXT,
    route_long_name      TEXT,
    route_type           INTEGER NOT NULL,
    route_color          TEXT,
    route_desc           TEXT,
    route_url            TEXT,
    route_text_color     TEXT,
    route_sort_order     INTEGER,
    continuous_pickup    INTEGER,
    continuous_drop_off  INTEGER,
    network_id           TEXT
);

CREATE TABLE shapes(
    shape_id           TEXT PRIMARY KEY,
    point_count        INTEGER NOT NULL,
    min_lat            REAL NOT NULL,
    min_lon            REAL NOT NULL,
    max_lat            REAL NOT NULL,
    max_lon            REAL NOT NULL,
    max_dist_traveled  REAL
);

CREATE TABLE shape_points(
    shape_id             TEXT NOT NULL REFERENCES shapes(shape_id),
    shape_pt_lat         REAL NOT NULL,
    shape_pt_lon         REAL NOT NULL,
    shape_pt_sequence    INTEGER NOT NULL,
    shape_dist_traveled  REAL
);

CREATE TABLE trips(
    trip_id                TEXT PRIMARY KEY,
    route_id               TEXT NOT NULL REFERENCES routes(route_id),
    service_id             TEXT NOT NULL,
    trip_headsign          TEXT,
    direction_id           INTEGER,
    shape_id               TEXT REFERENCES shapes(shape_id),
    trip_short_name        TEXT,
    block_id               TEXT,
    wheelchair_accessible  INTEGER,
    bikes_allowed          INTEGER
);

CREATE TABLE stop_times(
    trip_id              TEXT    NOT NULL REFERENCES trips(trip_id),
    arrival_time         TEXT,
    departure_time       TEXT,
    stop_id              TEXT    NOT NULL REFERENCES stops(stop_id),
    stop_sequence        INTEGER NOT NULL,
    pickup_type          INTEGER,
    drop_off_type        INTEGER,
    stop_headsign        TEXT,
    continuous_pickup    INTEGER,
    continuous_drop_off  INTEGER,
    shape_dist_traveled  REAL,
    timepoint            INTEGER,
    fare_stage           INTEGER,
    stop_dist            REAL
);

CREATE TABLE calendar(
    service_id  TEXT PRIMARY KEY,
    monday      INTEGER,
    tuesday     INTEGER,
    wednesday   INTEGER,
    thursday    INTEGER,
    friday      INTEGER,
    saturday    INTEGER,
    sunday      INTEGER,
    start_date  TEXT,
    end_date    TEXT
);

CREATE TABLE calendar_dates(
    service_id      TEXT,
    date            TEXT,
    exception_type  INTEGER,
    PRIMARY KEY (service_id, date)
);

CREATE TABLE frequencies(
    trip_id       TEXT NOT NULL REFERENCES trips(trip_id),
    start_time    TEXT NOT NULL,
    end_time      TEXT NOT NULL,
    headway_secs  INTEGER NOT NULL,
    exact_times   INTEGER,
    PRIMARY KEY (trip_id, start_time)
);

CREATE TABLE transfers(
    from_stop_id       TEXT,
    to_stop_id         TEXT,
    from_route_id      TEXT,
    to_route_id        TEXT,
    from_trip_id       TEXT,
    to_trip_id         TEXT,
    transfer_type      INTEGER NOT NULL,
    min_transfer_time  INTEGER
);

CREATE TABLE pathways(
    pathway_id              TEXT PRIMARY KEY,
    from_stop_id            TEXT NOT NULL REFERENCES stops(stop_id),
    to_stop_id              TEXT NOT NULL REFERENCES stops(stop_id),
    pathway_mode            INTEGER NOT NULL,
    is_bidirectional        INTEGER NOT NULL,
    length                  REAL,
    traversal_time          INTEGER,
    stair_count             INTEGER,
    max_slope               REAL,
    min_width               REAL,
    signposted_as           TEXT,
    reversed_signposted_as  TEXT
);

CREATE TABLE attributions(
    attribution_id     TEXT,
    agency_id          TEXT,
    route_id           TEXT,
    trip_id            TEXT,
    organization_name  TEXT NOT NULL,
    is_producer        INTEGER,
    is_operator        INTEGER,
    is_authority       INTEGER,
    attribution_url    TEXT,
    attribution_email  TEXT,
    attribution_phone  TEXT
);

CREATE TABLE fare_attributes(
    fare_id            TEXT PRIMARY KEY,
    price              REAL NOT NULL,
    currency_type      TEXT NOT NULL,
    payment_method     INTEGER NOT NULL,
    transfers          INTEGER,
    agency_id          TEXT,
    transfer_duration  INTEGER
);

CREATE TABLE fare_rules(
    fare_id         TEXT NOT NULL,
    route_id        TEXT,
    origin_id       TEXT,
    destination_id  TEXT,
    contains_id     TEXT
);

CREATE TABLE feed_info(
    feed_info_id         INTEGER PRIMARY KEY,
    feed_publisher_name  TEXT NOT NULL,
    feed_publisher_url   TEXT NOT NULL,
    feed_lang            TEXT NOT NULL,
    default_lang         TEXT,
    feed_start_date      TEXT,
    feed_end_date        TEXT,
    feed_version         TEXT,
    feed_contact_email   TEXT,
    feed_contact_url     TEXT
);

CREATE TABLE import_meta(
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

# Created AFTER the bulk load: building an index once over sorted data is much faster than
# maintaining it row by row, and the UNIQUE indexes are only created once duplicates have been
# ruled out (with a precise error report).
UNIQUE_INDEXES_DDL = """
CREATE UNIQUE INDEX idx_stoptimes_trip_seq  ON stop_times(trip_id, stop_sequence);
CREATE UNIQUE INDEX idx_shape_points_seq    ON shape_points(shape_id, shape_pt_sequence)
"""

INDEXES_DDL = """
CREATE INDEX idx_stoptimes_stop_dep  ON stop_times(stop_id, departure_time);
CREATE INDEX idx_trips_route_service ON trips(route_id, service_id);
CREATE INDEX idx_calendar_dates      ON calendar_dates(date, service_id)
"""

# Columns each table must expose for the Phase 0 API to function (health checks). Kept to the
# Phase 0 set on purpose: a version-1 database is still *servable* for the Phase 0 endpoints.
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "stops": ("stop_id", "stop_name", "stop_lat", "stop_lon"),
    "routes": ("route_id", "route_short_name", "route_long_name"),
    "trips": ("trip_id", "route_id", "service_id"),
    "stop_times": ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
    "calendar": ("service_id", *WEEKDAYS, "start_date", "end_date"),
    "calendar_dates": ("service_id", "date", "exception_type"),
}

# Derived tables: not backed by a file of their own.
DERIVED_TABLES = ("shapes",)


def spec_columns(table: str) -> tuple[str, ...]:
    """Columns the loader writes for ``table`` (used by the schema/spec consistency test)."""
    for spec in TABLE_SPECS:
        if spec.table == table:
            return spec.column_names
    raise KeyError(table)
