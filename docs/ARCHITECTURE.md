# CrowdSense – engineering architecture (Phase 0 foundation + Phase 1 GTFS data layer)

## Scope
Static GTFS only. No crowd/ETM data, no live vehicle tracking; routing is direct scheduled trips. Crowd values are
never invented: the journey response always says `NOT_AVAILABLE`.

### Five different kinds of data (do not conflate them)
| Kind | What it is | In CrowdSense today |
|---|---|---|
| **Static schedule (GTFS)** | The *planned* timetable and network geometry published by the agency: stops, routes, trips, planned times, service calendars, shapes | **Yes** – the only data source. It describes what is *supposed* to run |
| **Actual vehicle operations** | Where buses really are, real arrival times, delays, cancellations, breakdowns (GTFS-Realtime / AVL) | **No.** Static GTFS contains no vehicle positions; a scheduled departure is not a prediction |
| **Passenger ticket data** | ETM / e-ticketing transactions: boardings and alightings per ticket | **No** – not yet obtained |
| **Historical passenger load** | Typical occupancy per trip/segment/time, *reconstructed from* ticket data | **No** – needs ticket data first |
| **Live crowd information** | How full a bus is *now* | **No** – needs live occupancy or live tickets; nothing in static GTFS implies it |

Static GTFS lets us say *"a bus is scheduled at 08:10"*. It cannot say *"it is running"*, *"it is 5 minutes late"* or
*"it is crowded"*. The API repeats this in `GET /gtfs/summary` (`data_scope`) and in departure responses.

## Responsibilities
| Layer | Module(s) | Responsibility |
|---|---|---|
| Configuration | `app/config.py` | Read + validate env once; relative paths anchored to `backend/` |
| HTTP | `app/api/*`, `app/schemas.py` | Routing, request validation, response models, structured errors |
| Services | `app/services/*` | Stops/departures, network (agencies, routes, trips, stop times), shapes, summary/validation report, journeys, health (no HTTP concepts except `AppError`) |
| Database access | `app/db.py` | Only code that opens SQLite: pragmas, close-on-exit, explicit transactions |
| GTFS | `app/gtfs/*` | `spec.py` (declarative file specs), `archive.py`, table-driven streaming `loader.py`, `validation.py` (findings engine), `calendar.py` (service dates), staged `importer.py`, `schema.py` |
| CLI | `scripts/import_gtfs.py`, `scripts/benchmark_queries.py` | Importer wrapper; read-only query benchmark with query plans |

## Request data flow
`request → router (validation) → get_db (read-only connection, closed after response) → service SQL → Pydantic model → JSON`.
Errors raise `AppError`/`DatabaseUnavailableError`/`sqlite3.Error`, converted by `api/error_handlers.py` to
`{"error": {...}, "detail": ...}`; unexpected exceptions are logged with traceback and answered generically.

## Import data flow
```
ZIP → inspect_archive (CRC, files, headers of EVERY supported file, extension/unsupported columns) → build <db>.staging  [ONE transaction]
        load agency→stops→routes→levels→trips→calendar(+_dates)→shape_points→stop_times→frequencies→transfers→pathways→attributions→fares→feed_info
            (spec-driven streaming parsers, batch 50k, row validation, per-file accounting)
        → duplicate-key checks → UNIQUE indexes → derived shapes summary → other indexes
        → validation engine: references, schedule, calendar, shapes, agency/feed, column usage  (error/warning/info)
        → import_meta (counts + the full data-quality report, inside the data) → PRAGMA user_version = 2
      COMMIT → WAL + checkpoint + fsync + quick_check
→ promote: checkpoint live DB → hard-link live → <db>.previous.tmp → os.replace(staging, live) → rename previous
           → verify ALL table counts/quick_check (restore on failure)
→ write <db>.import-status.json   (import STATUS - kept separate from the data-quality report inside the DB)
```
Locking: `<db>.import.lock` (exclusive create) prevents concurrent imports. Details: [GTFS_INGESTION.md](GTFS_INGESTION.md).

## Service-date engine
`gtfs/calendar.py`: `get_active_service_ids(conn, date)` and `evaluate_services(...)` implement `calendar.txt` (weekday +
inclusive range) then `calendar_dates.txt` overrides, work without either file, and never assume a trip runs every day.
The Phase 0 journey service delegates to it (one implementation). GTFS times past 24:00 belong to the starting service
day; `/stops/{id}/departures` handles this by also evaluating the previous day. The Phase 0 *journey search* still does not
(see limitations).

## Geometry
`shapes` (derived summary) + `shape_points` (ordered points). `/trips/{id}/shape` returns real points only; a trip without
a shape is reported explicitly, with an opt-in, clearly labelled stop-sequence fallback. No GIS extension is used.

## Database
Schema version 2 (`PRAGMA user_version = 2`): 17 GTFS tables plus `import_meta`; the Phase 0 tables keep their names and
columns. See [GTFS_DATA_MODEL.md](GTFS_DATA_MODEL.md). Connection settings: `busy_timeout=5000`, `foreign_keys=ON`,
`synchronous=NORMAL`, `journal_mode=WAL` (stored in the file), API connections `query_only`. A version-1 database still
serves the Phase 0 endpoints; Phase 1 endpoints answer `503 schema_outdated` until the feed is re-imported.

**Index review** (measured on the real feed, evidence in [PERFORMANCE.md](PERFORMANCE.md)): `idx_stoptimes_stop` became
`idx_stoptimes_stop_dep (stop_id, departure_time)` (departures at a stop 3.7 ms → 0.02 ms, +23 MB, slower stop-detail query at
the very busiest stop); `idx_stoptimes_trip_seq` and `idx_shape_points_seq` are UNIQUE (they enforce the GTFS keys at no extra
index cost); `idx_trips_route_service` now serves route endpoints; `trips(shape_id)` was measured and rejected.
Stop search is a leading-wildcard LIKE over ~6.8k rows (≈1 ms; not indexable).

Time normalisation: stored `HH:MM:SS` with zero-padded hours (may exceed 23), so string order equals time order.

## Future PostgreSQL migration considerations (not done)
Keep SQL in services, ANSI-friendly; `stop_times` becomes the partition/ingest hot spot (COPY instead of executemany);
text times → `interval`/seconds ints; replace file-swap promotion with a schema swap or `import_id` versioning; add
a connection pool; move crowd tables (later phases) behind the same service boundary.
