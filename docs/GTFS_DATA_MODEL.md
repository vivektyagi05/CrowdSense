# GTFS data model (schema version 2)

Source of truth: `backend/app/gtfs/schema.py` (DDL) and `backend/app/gtfs/spec.py` (per-file column specs). A unit test
asserts that every column the loader writes exists in the DDL, so the two cannot drift.

Reference: the official GTFS Schedule specification, <https://gtfs.org/documentation/schedule/reference/>.

## File → table mapping

| GTFS file | Table | Rows (Delhi feed) | Notes |
|---|---|---:|---|
| `agency.txt` | `agency` | 2 | `agency_id = ''` stores the single agency of a feed that omits `agency_id` |
| `stops.txt` | `stops` | 6,812 | all standard optional columns (`stop_code`, `zone_id`, `parent_station`, `level_id` …) |
| `routes.txt` | `routes` | 2,554 | `route_type` is an `INTEGER` |
| `trips.txt` | `trips` | 65,322 | `shape_id` → `shapes` |
| `stop_times.txt` | `stop_times` | 2,385,381 | plus extension columns `fare_stage`, `stop_dist` |
| `calendar.txt` | `calendar` | 1 | |
| `calendar_dates.txt` | `calendar_dates` | 0 | **absent in the Delhi feed**; fully supported when present |
| `shapes.txt` | `shape_points` | 765,633 | one row per point |
| *(derived)* | `shapes` | 2,554 | summary per `shape_id`: point count, bounding box, max distance |
| `feed_info.txt` | `feed_info` | 2 | the GTFS spec allows one row; Delhi publishes two (one per agency). All are stored |
| `frequencies.txt` | `frequencies` | – | supported, absent in Delhi |
| `transfers.txt` | `transfers` | – | supported, absent |
| `levels.txt`, `pathways.txt` | `levels`, `pathways` | – | supported, absent |
| `attributions.txt` | `attributions` | – | supported, absent |
| `fare_attributes.txt`, `fare_rules.txt` | `fare_attributes`, `fare_rules` | – | supported (Fares v1), absent |
| `translations.txt`, Fares v2 files, `areas`, `networks`, `location_groups`, `booking_rules`, `locations.geojson` … | – | – | valid GTFS, **not imported**; reported as `recognised_file_not_imported` if present |
| `import_meta` | `import_meta` | – | key/value: schema version, source SHA-256, per-table counts, the validation report |

Optional files that are absent produce empty tables and an *info* finding. **Nothing is invented for a missing file.**

## Relationships

```
agency ─┐
        └< routes >──< trips >──< stop_times >── stops ──(parent_station)── stops
                       │  └─ service_id ··· calendar / calendar_dates (no FK, see below)
                       └─ shape_id >── shapes ──< shape_points
trips ──< frequencies          stops ──< transfers / pathways         fare_attributes ──< fare_rules
```

* **Declared foreign keys** (documentation + protection for future writers): `trips.route_id`, `trips.shape_id`,
  `stop_times.trip_id`, `stop_times.stop_id`, `stops.parent_station`, `shape_points.shape_id`, `frequencies.trip_id`,
  `pathways.from/to_stop_id`.
* **Verified set-based after loading** (every relationship, including those that cannot be declared): see
  [VALIDATION_RULES.md](VALIDATION_RULES.md). The bulk load runs with `foreign_keys=OFF` so one bad row does not hide all
  the others; the checks then give a complete report.
* `service_id` is **not** a foreign key: GTFS lets it be defined in `calendar.txt` *or* `calendar_dates.txt`.
* `routes.agency_id → agency` is not declared because `agency.txt` can legitimately be missing from older feeds; it is
  checked when both exist.

## Keys and constraints

| Table | Key |
|---|---|
| `agency` | `agency_id` |
| `stops`, `routes`, `trips`, `levels`, `pathways`, `fare_attributes`, `shapes` | the GTFS id (PRIMARY KEY) |
| `calendar` | `service_id` |
| `calendar_dates` | `(service_id, date)` |
| `frequencies` | `(trip_id, start_time)` |
| `stop_times` | UNIQUE `(trip_id, stop_sequence)` (index `idx_stoptimes_trip_seq`) |
| `shape_points` | UNIQUE `(shape_id, shape_pt_sequence)` (index `idx_shape_points_seq`) |
| `feed_info` | surrogate `feed_info_id` (row ordinal) |

The two big tables get their UNIQUE index **after** the load and only once a set-based duplicate check has passed, so a
duplicate produces a precise report instead of an opaque constraint error.

## Type decisions

| Concern | Decision |
|---|---|
| Identifiers | always `TEXT`, never converted (`"0012"` stays `"0012"`) |
| `stop_sequence`, `shape_pt_sequence` | `INTEGER`; sparse values (1, 5, 9) are kept exactly |
| Coordinates | `REAL` (IEEE-754 double, ~15–17 significant digits). Stop coordinates keep all 14 digits Delhi publishes |
| Times | `TEXT` `HH:MM:SS`, hours may exceed 23 (Delhi has 22,719 rows with hours 24–28). Zero-padded so string order = time order. Empty (non-timepoint) times stay `NULL` and are **not interpolated** |
| Dates | `TEXT` `YYYYMMDD`, validated as real calendar dates |
| Enumerations | `INTEGER` (`route_type`, `location_type`, `direction_id`, `pickup_type`, `drop_off_type`, `timepoint`, …). Phase 0 stored some as TEXT digits |
| Empty optional values | `NULL` (e.g. `fare_attributes.transfers` empty = unlimited transfers) |
| Extension columns | stored when this feed uses them (`stop_times.fare_stage`, `stop_dist`); any *other* unknown column is reported, **not** stored |

## Indexes

| Index | Columns | Serves |
|---|---|---|
| (PK / UNIQUE autoindexes) | ids | lookups by id |
| `idx_stoptimes_trip_seq` UNIQUE | `stop_times(trip_id, stop_sequence)` | ordered stop times of a trip; trip edges; window checks |
| `idx_stoptimes_stop_dep` | `stop_times(stop_id, departure_time)` | everything at a stop; time-ordered departures as a range scan (leftmost prefix also serves plain `stop_id` lookups) |
| `idx_shape_points_seq` UNIQUE | `shape_points(shape_id, shape_pt_sequence)` | a whole shape in order |
| `idx_trips_route_service` | `trips(route_id, service_id)` | trips of a route (optionally per service) |
| `idx_calendar_dates` | `calendar_dates(date, service_id)` | exceptions for one date |

Evidence, rejected candidates and measured trade-offs: [PERFORMANCE.md](PERFORMANCE.md).

## What changed versus Phase 0 (audit)

Phase 0 imported 5 of the 8 files in the archive (and only the metadata of a sixth):

| | Phase 0 (schema v1) | Phase 1 (schema v2) |
|---|---|---|
| Files | stops, routes, trips, stop_times, calendar (+ `calendar_dates` if present). `feed_info` read for 4 metadata keys only. **`agency.txt` and `shapes.txt` ignored** | all 8 present files, plus 8 optional file types when present |
| `stops` | stop_id, stop_name, stop_lat, stop_lon, location_type | + code, desc, zone, url, parent_station, timezone, wheelchair_boarding, level_id, platform_code |
| `routes` | route_id, agency_id, short/long name, route_type, route_color | + route_desc, url, text colour, sort order, continuous pickup/drop-off, network_id |
| `trips` | trip_id, route_id, service_id, trip_headsign, direction_id, shape_id | + trip_short_name, block_id, wheelchair_accessible, bikes_allowed |
| `stop_times` | 7 columns | + stop_headsign, continuous pickup/drop-off, shape_dist_traveled, timepoint, **fare_stage**, stop_dist |
| Shapes | none (a `shape_id` string on trips pointing at nothing) | `shapes`, `shape_points` |
| Enumerations | TEXT | INTEGER |
| Index on `stop_times` | `(stop_id)` | `(stop_id, departure_time)` |
