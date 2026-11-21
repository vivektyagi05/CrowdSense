# HTTP API (`/api/v1`)

Interactive documentation: <http://127.0.0.1:8000/docs>. All endpoints are `GET`, read-only, and return JSON built from
the imported database. **Responses are always bounded**: list endpoints are paginated with `limit`/`offset` and cap
`limit`. Errors: `{"error": {"code", "message", "details?"}, "detail": "<message>"}`.

Phase 0 endpoints (`/health`, `/health/live`, `/journeys`, `/stops?q=`) are unchanged in behaviour, except that
`GET /stops` no longer requires `q` (it lists stops). Phase 1 endpoints need a **schema-version-2** database; a Phase 0
database answers `503 schema_outdated` (run `python -m scripts.import_gtfs`).

Paginated responses carry `total` (rows matching the filters), `limit`, `offset`.

| Endpoint | Purpose | Parameters (default / max) |
|---|---|---|
| `GET /agencies` | agencies | – |
| `GET /stops` | search / list stops (items keep the Phase 0 4-field shape) | `q` (≥2 chars), `bbox=min_lon,min_lat,max_lon,max_lat`, `route_id`, `limit` (20/**50**), `offset` |
| `GET /stops/{stop_id}` | one stop + every route serving it (+ scheduled call count) | – |
| `GET /stops/{stop_id}/departures` | next *scheduled* departures, midnight-correct | `date` (today in feed tz), `after` (`HH:MM[:SS]`), `limit` (20/100) |
| `GET /routes` | list routes | `q`, `agency_id`, `route_type`, `limit` (50/200), `offset` |
| `GET /routes/{route_id}` | route + agency + trip/stop counts, services, directions, shapes | – |
| `GET /routes/{route_id}/trips` | trips with first departure | `service_id`, `limit` (50/200), `offset` |
| `GET /routes/{route_id}/shapes` | distinct shapes used by the route | – |
| `GET /trips/{trip_id}` | trip + route names + first/last stop | – |
| `GET /trips/{trip_id}/stop-times` | ordered stop times with stop names/coordinates | `limit` (100/**500**), `offset` |
| `GET /trips/{trip_id}/shape` | the trip's actual GTFS shape | `format=points\|geojson`, `fallback=stops`, `limit` (5000/50000), `offset` |
| `GET /shapes/{shape_id}` | a shape by id | `format`, `limit`, `offset` |
| `GET /services/active` | service ids running on a date, with reasons | `date`, `include_inactive` |
| `GET /gtfs/summary` | what the feed contains, calendar, shapes, data-quality status, data scope | – |
| `GET /gtfs/validation-report` | findings + every integrity check + per-file accounting | – |
| `GET /health`, `/health/live`, `GET /journeys` | unchanged from Phase 0 | |

The 2.4-million-row `stop_times` table is only ever exposed one trip at a time, in pages.

## Shapes: geometry is never invented

`/trips/{id}/shape` returns the feed's own points ordered by `shape_pt_sequence`
(`geometry_source: "gtfs_shape"`). If the trip has no usable shape the response says so explicitly:

```json
{"trip_id":"T3","shape_available":false,"geometry_source":"none","reason":"trip_has_no_shape_id","points":[], "...":"..."}
```

Documented fallback for later map work: `?fallback=stops` returns the trip's stops in sequence, labelled
`geometry_source: "stop_sequence_fallback"` with a note that straight segments between stops are **not** the road
geometry. A trip that has a shape never receives the fallback. `format=geojson` returns a `LineString` Feature
(coordinates are `[lon, lat]`). `shape_dist_traveled` is in the feed's own, unspecified unit.

## Phase 4 additions (additive; real examples in `docs/phase4/API_CHANGES.md`)

* `GET /trips/{id}/shape?from_stop_id=&to_stop_id=[&board=HH:MM[:SS]][&tolerance_m=]` returns the slice of the trip's GTFS shape between
  two of its stops, simplified (Ramer-Douglas-Peucker in metres, default 5 m, clamped 1-50 m). `status` is `ok`, `no_shape` or
  `unreliable_projection` (a stop farther than 60 m from the shape, or an impossible order): the latter two return **no coordinates**.
  Loop trips pick the correct call (`board` selects the boarding call; alighting is the first later call). The `fallback=stops` option
  of the plain endpoint is a straight line between stops and is never used by the UI.
* `GET /routes/{id}/shapes?geometry=true[&tolerance_m=][&max_points=]` adds simplified `coordinates` per shape (hard point cap).
* `GET /stops/nearby?lat=&lon=[&radius_m=50-3000][&limit=1-50]`: stops nearest first with `distance_m`, `bearing_deg`, `compass`,
  `routes_count`, `route_names`. Points outside 28.00-29.50 N, 76.40-77.80 E return 422 `location_out_of_area`. Coordinates are not logged.
* `GET /clusters/{id}`: the physical stops sharing one place name (same normalised name, complete linkage <= 150 m) with real
  distinguishing data. `cluster_id` appears on `/stops/{id}` and `/stops` items when derived data is built (`python -m scripts.build_derived`).
* `GET /stops?q=&mode=smart[&limit=]`: normalised, typo-tolerant (<= 2 edits for tokens >= 5 characters), ranked
  (`exact > alias > prefix > all_tokens > fuzzy > partial_tokens`), grouped by place cluster; every hit carries `match_type` and `score`.

## Service dates

`/services/active?date=2026-11-10&include_inactive=true` evaluates `calendar.txt` (weekday flag + inclusive date range),
then `calendar_dates.txt` (1 = add, 2 = remove) for that date. Each service carries a reason: `weekly_calendar`,
`added_by_exception`, `removed_by_exception`, `outside_calendar_date_range`, `weekday_not_scheduled`,
`not_added_on_this_date`, `no_calendar_definition`. Without `date`, "today" is computed in the agency timezone
(needs the tz database: the `tzdata` package is installed automatically on Windows).

GTFS times past 24:00:00 belong to the service day the trip started. `/stops/{id}/departures` therefore also looks at
the *previous* service day's trips (a 25:10:00 call yesterday is 01:10 today); each item shows its `service_date`.

## Examples from the real Delhi database

```text
GET /trips/1_06_05            -> route 1, 36 stops, first stop sequence 0 (Rohini Sec 22 Terminal)
GET /trips/1_06_05/shape      -> shape shp_3_2029 (gtfs_shape), N points, all trips have shapes
GET /stops/115                -> 4,192 scheduled calls, 139 routes
GET /services/active?date=2026-11-09  -> ["1"]      GET /services/active?date=2040-01-02 -> []
GET /gtfs/summary             -> 2,554 shapes / 765,633 points, 0 calendar exceptions, quality pass_with_warnings
```

## Static schedule is not live operations

These endpoints describe the **planned timetable**. They contain no vehicle positions, delays or cancellations, no
ticket (ETM) data, no historical passenger loads and no live crowd information. `GET /gtfs/summary` repeats this in
`data_scope`, and `/stops/{id}/departures` carries a `notice` that times are scheduled, not predicted.
