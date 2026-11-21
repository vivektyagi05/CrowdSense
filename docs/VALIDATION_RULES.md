# Validation rules

Implemented in `backend/app/gtfs/{archive,loader,validation}.py`. Three severities, never mixed:

* **error** – violates the GTFS specification in a way that makes the feed unsafe to use. **Aborts the import**; the served
  database is untouched.
* **warning** – suspicious or spec-discouraged, but does not prevent correct use. Always recorded.
* **info** – neutral facts (extension columns, overnight service, absent optional files).

Rules follow the official GTFS Schedule reference. Valid-but-uncommon features are accepted: times past 24:00:00,
sparse `stop_sequence`, missing `calendar_dates.txt`, missing `agency_id` in a single-agency feed, empty
non-timepoint times, `calendar_dates`-only services, `location_type` 3/4 nodes without coordinates.

*This is not a claim that a feed is fully GTFS-compliant.* It is the set of checks listed here. Run the official
MobilityData validator for a certification-grade opinion.

## 1. Archive and header checks (fatal)

ZIP readable and CRC-clean · expands below the safety limit · exactly one GTFS root folder · `stops`, `routes`, `trips`,
`stop_times` present · `calendar` and/or `calendar_dates` present · every present supported file: non-empty, valid UTF-8,
no duplicate or empty header names, all required columns present, `routes.txt` has a short or long name column.

## 2. Row-level checks (fatal; reported with file, line, reason)

Column count matches the header · required values non-empty · integers, bounded numbers, enumerations (e.g. `pickup_type`
0–3, `exception_type` 1–2) · latitude/longitude ranges · real calendar dates · times `H:MM:SS` (hours unbounded) ·
URLs (`http`/`https`), emails, language codes, 6-digit hex colours, currency codes · duplicate primary keys
(`stop_id`, `trip_id`, `service_id`, `(service_id, date)`, …) · `calendar.start_date <= end_date` ·
`frequencies.end_time > start_time` · stop: name/coordinates required for `location_type` 0–2, lat/lon given together ·
route: needs a short or long name · `transfers`: stops required for types 1–3, trips for types 4–5 · `attributions`:
at least one role flag, only one of agency/route/trip.

## 3. Duplicate keys (fatal, before UNIQUE indexes)

| Code | Meaning |
|---|---|
| `duplicate_stop_time_sequence` | repeated `(trip_id, stop_sequence)` |
| `duplicate_shape_point_sequence` | repeated `(shape_id, shape_pt_sequence)` |

## 4. Referential integrity (fatal unless noted)

Every check is recorded as `passed`, `failed` or `skipped` (child table empty, or parent file legitimately absent).

`trip_route_missing` · `trip_shape_missing` (a `shape_id` with no `shapes.txt` is an error) · `trip_service_missing`
(`service_id` in neither calendar file) · `stop_time_trip_missing` · `stop_time_stop_missing` · `route_agency_missing`
(skipped when `agency.txt` is absent) · `route_agency_required` (several agencies but a route without `agency_id`) ·
`stop_parent_missing` · `stop_parent_required` (`location_type` 2/3/4 needs a parent) · `stop_level_missing` ·
`frequency_trip_missing` · `transfer_{from,to}_{stop,route,trip}_missing` · `pathway_{from,to}_stop_missing` ·
`attribution_{agency,route,trip}_missing` · `fare_rule_fare_missing` · `fare_rule_route_missing` · `fare_agency_missing`.

## 5. Schedule validation

| Code | Severity | Rule |
|---|---|---|
| `departure_before_arrival` | error | `departure_time < arrival_time` on one stop_time |
| `time_travel` | error | a stop's time is earlier than the previous stop's departure (in `stop_sequence` order) |
| `stop_time_dist_decreasing` | error | `shape_dist_traveled` decreases along a trip |
| `trip_edge_time_missing` | error | first or last stop_time of a trip has neither arrival nor departure time |
| `consecutive_duplicate_stop` | warning | a stop_time serves the same stop as the previous one |
| `trip_too_short` | warning | trip with fewer than 2 stop_times (Phase 0 wording kept) |
| `unused_stops` | warning | stop (location_type 0) never served |
| `routes_without_trips` | warning | route with no trips |
| `stop_at_null_island` | warning | coordinates exactly (0, 0) |
| `overnight_service` | info | rows with hours ≥ 24 (belong to the service day the trip started) |

Times are compared as zero-padded text, which is exact for hours up to 99.

## 6. Calendar validation

| Code | Severity | Rule |
|---|---|---|
| `no_service_calendar` | error | neither calendar file has any row |
| `calendar_never_active` | warning | all weekday flags 0 and no added dates |
| `calendar_removal_without_base` | warning | removal exception for a service with no calendar row |
| `calendar_unused_service` / `calendar_dates_unused_service` | info | service used by no trip |
| `calendar_span` / `calendar_absent` / `calendar_dates_absent` | info | facts about the calendar files |

## 7. Shapes

`shape_too_short` (warning, < 2 points) · `shape_point_dist_decreasing` (error) · `unused_shapes` (info) ·
`trips_without_shape` (warning: shapes exist but some trips have no `shape_id`; their geometry is unknown) ·
`shapes_absent` (info: no geometry is available and none is invented).

## 8. Agency and feed

`agency_file_missing` (warning – agency.txt is required by the spec; tolerated for compatibility with Phase 0 feeds) ·
`agency_timezone_consistent` (error: all agencies must share one timezone) · `feed_info_multiple_rows` (warning) ·
`feed_info_date_order` (error) · `feed_info_missing` / `single_agency` (info).

## 9. Archive / column findings

`optional_file_absent` (info) · `recognised_file_not_imported` (warning) · `unrecognised_file` (warning) ·
`unsupported_columns` (warning) · `extension_column_stored` (info) · `extension_column_empty` (info) ·
`duplicate_stop_names` / `duplicate_stop_locations` (info – legitimate, but routing must use `stop_id`).

## Findings on the real Delhi feed

0 errors. 2 warnings: `feed_info_multiple_rows` (2 rows, 1 expected) and `consecutive_duplicate_stop` (1,846 stop_times,
e.g. `1184_07_14` at sequence 24 — the same stop repeated back to back; looks like a terminus/loop artefact, left
untouched). 15 info findings. Integrity checks: 30 passed, 1 reported a finding, 15 skipped (optional tables empty).

## Not validated (known gaps)

* Stops far from their trip's shape; speeds implied by times/distances; trips with identical stop patterns.
* Interpolation of empty `arrival_time`/`departure_time` for non-timepoints.
* Time zone names are not checked against the tz database.
* Fares v2, translations, `locations.geojson`.
