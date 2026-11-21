# Changelog

## Phase 4: geospatial platform, real route geometry, smart place discovery

All API changes are additive (see `docs/phase4/API_CHANGES.md`); no Phase 3 test was removed or weakened.

### Backend
* `GET /trips/{id}/shape?from_stop_id&to_stop_id[&board][&tolerance_m]`: leg geometry from the real GTFS shape (monotone Viterbi stop matching, loop-safe, RDP simplification in metres); structured `no_shape` / `unreliable_projection`, never a guess.
* `GET /routes/{id}/shapes?geometry=true` (capped, simplified); `GET /stops/nearby` (R-tree, grid or scan fallback; validated Delhi-NCR box); `GET /clusters/{id}`; `GET /stops?mode=smart`; additive `cluster_id` on stop responses.
* `python -m scripts.build_derived`: idempotent, deterministic derived data (spatial index, stop-routes, place clusters, content hash). Run after every GTFS import.
* **Privacy fix:** uvicorn access logs recorded full query strings; `lat`/`lon` values are now redacted (tested against a real server process).
* Dev dependency: `hypothesis==6.170.13` (property tests). No new runtime Python dependency.

### Frontend
* MapLibre GL JS 6.16.0 behind a thin adapter, lazy-loaded (entry chunk -2.31 kB gzip vs Phase 3); maps on journey details, route, stop and the new `/nearby` page; honest handling of missing geometry; no WebGL / no style URL / tile failure / slow network fallbacks.
* Cluster-aware autocomplete, saved and recent places (device-local, stop ids only), explicit-click geolocation, pick-on-map.
* `VITE_MAP_STYLE_URL` (no default tile provider).

### Known gaps
See `docs/phase4/GAPS.md`: notably **no real browser was available, so visual/WebGL behaviour is unverified**.

## 0.3.0 – Phase 1: complete GTFS data engineering layer

### Ingestion
* Imports **every** supported file present in the Delhi archive: `agency`, `stops`, `routes`, `trips`, `stop_times`, `calendar`, **`shapes`** (765,633 points), **`feed_info`**; plus `calendar_dates`, `frequencies`, `transfers`, `levels`, `pathways`, `attributions`, `fare_attributes`, `fare_rules` when present. Absent optional files are reported, never invented.
* Table-driven loader generated from `app/gtfs/spec.py`; all standard optional columns are stored. Non-standard `stop_times.fare_stage`/`stop_dist` are stored and reported; other unknown columns are reported, not stored. Unimported GTFS files are reported.
* Schema version 2 (`PRAGMA user_version = 2`). Phase 0 table/column names are unchanged; new tables `agency, shapes, shape_points, feed_info, levels, frequencies, transfers, pathways, attributions, fare_attributes, fare_rules`. GTFS enumerations are `INTEGER` (were TEXT digits).
* Index change: `idx_stoptimes_stop(stop_id)` → `idx_stoptimes_stop_dep(stop_id, departure_time)` (measured, see `docs/PERFORMANCE.md`); `idx_shape_points_seq` UNIQUE added.

### Validation and reporting
* New findings engine (error / warning / info) with a pass/fail/skip record for **every** integrity check; referential integrity across all files; schedule checks (times, ordering, shape distances, trip edges); calendar and shape checks. Import report split into *import status* and *data quality*; the data-quality report is stored inside the database.
* Real Delhi feed: 0 errors, 2 warnings (`feed_info` has 2 rows; 1,846 repeated consecutive stops), 15 info findings.

### Service dates and geometry
* `app/gtfs/calendar.py`: `get_active_service_ids` / `evaluate_services` (weekly calendar, added and removed exceptions, calendar-dates-only feeds, reasons). The journey service now delegates to it.
* Real route geometry via `/trips/{id}/shape`, `/shapes/{id}`, `/routes/{id}/shapes` (points or GeoJSON); explicit missing-shape report with an opt-in labelled fallback.

### API (all new endpoints under `/api/v1`)
`/agencies`, `/stops/{id}`, `/stops/{id}/departures`, `/routes`, `/routes/{id}`, `/routes/{id}/trips`, `/routes/{id}/shapes`, `/trips/{id}`, `/trips/{id}/stop-times`, `/trips/{id}/shape`, `/shapes/{id}`, `/services/active`, `/gtfs/summary`, `/gtfs/validation-report`. Paginated, bounded, response-validated.

### Behaviour changes (intentional)
| Area | Before | Now |
|---|---|---|
| `GET /stops` without `q` | `422` | lists stops (paginated). `q`, if given, still needs ≥2 non-blank characters; items keep the 4-field shape; `limit` max still 50; response gains `total/limit/offset` |
| Archive inspection | `agency.txt`/`shapes.txt` reported as "known but not imported" | imported; `ignored_known_files` now lists only recognised files still not imported (e.g. `translations.txt`) |
| `routes.txt` | `route_type` optional | required (GTFS) |
| Database | schema v1 | schema v2. A v1 database still serves Phase 0 endpoints; Phase 1 endpoints answer `503 schema_outdated` until re-imported |
| Import report | 6 table counts | `counts` unchanged + `table_counts` (17 tables), `file_details`, `data_quality`, … |

### Frontend
* Network summary / data-readiness panel (`/gtfs/summary`) and selected-stop details (`/stops/{id}`); both degrade quietly if the endpoints are unavailable. Stop search and the journey flow are unchanged.

### Tests
* Backend: 86 → 206 collected (197 run by default + 9 opt-in real-feed tests; was 85 + 1 skipped). Frontend: 24 → 33. Two Phase 0 tests were edited, both for the intentional contract changes tabled above (`test_known_unimported_files_reported`; `test_stop_search_limit_and_validation` no longer expects 422 for a missing `q`). All other Phase 0 tests are untouched and pass.

## 0.2.0 – Phase 0: engineering foundation

### Safety / data integrity
* **Importer no longer deletes the database.** Staged import → validate → atomic promote; failures leave the live DB untouched; previous DB kept as `*.previous`; WAL/SHM-aware; import lock; status file; post-promotion verification with automatic restore.
* Strict row validation: every malformed record is reported with file/line, none are silently dropped.
* `stop_times (trip_id, stop_sequence)` uniqueness now enforced (`idx_stoptimes_trip_seq` UNIQUE).

### Bug fixes (reproduced against the real Delhi data with the old code)
* Journey search returned **no results for late-day searches on busy stop pairs** (e.g. 115→7571 at 20:00): `LIMIT 1000` was applied before the time filter. Filtering is now in SQL.
* A departure with a UTC offset (`…+05:30`) caused **HTTP 500**; now a clear **400**.
* `lower(...) LIKE` treated `%`/`_` typed by users as wildcards; now literal.
* Frontend `npm run build` started the dev server instead of building; fixed. Stale out-of-order stop suggestions fixed with request cancellation.

### Behaviour changes (all intentional, documented)
| Area | Before | Now |
|---|---|---|
| Error body | `{"detail": ...}` | `{"error": {code, message}, "detail": same message}` (`detail` kept for compatibility) |
| `/health` | always 200; `status: ok/needs_setup`; raw exception text in `detail` | 200 only when DB+GTFS ready, else 503; adds `checks`, `version`, `timestamp`; legacy `status`, `gtfs_loaded`, `counts`, `crowd_engine` retained; new `/health/live` |
| `/journeys` unknown stop id | `200` empty list | `404 stop_not_found` |
| `/journeys` origin == destination | empty/loops | `400 same_stop` |
| `/journeys` ordering | arbitrary among equal departure times | deterministic (`departure, trip_id`) |
| `/stops` ordering | by name | by name, then `stop_id` |
| Stop search `q` | `"  "` accepted | blank rejected (422) |
| CORS | credentials allowed, all methods | no credentials, `GET/OPTIONS` only |
| Importer | `calendar` files both optional | at least one of `calendar.txt`/`calendar_dates.txt` required (GTFS spec) |
| Coordinates | text→REAL via SQLite | parsed by Python `float()` (correctly rounded). On the Delhi feed 2 of 6,812 stops differ by 1 ULP (3.6e-15°) from the old DB; all ids and all other values identical |

### Configuration, dependencies, repo
* Env-driven validated config (`.env.example`), `python -m app` entry point, structured logging.
* Backend deps fully pinned (`requirements.txt`, `requirements-dev.txt`); frontend deps pinned (no `latest`), lockfile regenerated, unused `lucide-react` removed, dev server now localhost-only with `strictPort`.
* `.gitignore`, README, `docs/ARCHITECTURE.md`, `scripts/verify.ps1`.

### Tests
* Backend: pytest suite (config, DB lifecycle, archive validation, importer safety, API). Frontend: Vitest + Testing Library.
