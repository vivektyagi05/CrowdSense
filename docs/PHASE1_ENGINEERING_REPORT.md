# Phase 1 engineering report – GTFS data engineering layer

Status legend: **VERIFIED** = executed and observed in the sandbox (Linux, Python 3.12, SQLite 3.45, Node 22) ·
**NOT VERIFIED** = written but not executed in this environment (see section 15).

## 1. Initial audit findings
* Phase 0 baseline reproduced before any edit: backend **85 passed, 1 skipped**; frontend **24 passed**. VERIFIED.
* Archive `delhi_buses_static_gtfs_v1.zip` holds 8 files under `delhi_buses_static_gtfs_v1-2/`. Phase 0 imported 5
  (stops, routes, trips, stop_times, calendar) and only 4 metadata keys of `feed_info.txt`. **`agency.txt` and `shapes.txt`
  (765,633 points, 2,554 shapes) were ignored**; `trips.shape_id` pointed at nothing.
* Phase 0 schema: 6 data tables + `import_meta`, `user_version = 1`; enumerations stored as TEXT; indexes
  `idx_stoptimes_stop(stop_id)`, UNIQUE `idx_stoptimes_trip_seq`, `idx_trips_route_service`, `idx_calendar_dates`.
* Phase 0 validation covered row syntax, `(trip_id, stop_sequence)` duplicates and 4 orphan checks. Missing: shapes,
  agency, any schedule consistency (time order), calendar sanity, extension columns, unsupported columns.
* Real-feed facts found by profiling (not assumed): calendar = 1 weekly service `1`, 2025-01-01…2040-01-01, no
  `calendar_dates.txt`; 2 agencies (DTC 1,619 routes, DOT 935); every route has `route_type 3`; **every trip has a `shape_id` and
  every one exists** (2,554 shapes, one per route); 22,719 stop_times use hours 24–28; `trip_headsign`, `direction_id`,
  `block_id`, `trip_short_name` empty for all trips; `stop_times.txt` carries non-GTFS columns `fare_stage` (0/1) and
  `stop_dist` (always empty); `feed_info.txt` has 2 rows; 1,846 stop_times repeat the previous stop.
* Compatibility constraints taken from the Phase 0 tests: `/stops` items keep exactly 4 keys and `limit ≤ 50`;
  `search_stops` stays the monkeypatched name; `report.counts` stays the six Phase 0 tables.

## 2. Files imported before / after
Before: 5 files (+ feed_info metadata). After: **8/8 present files** (`agency, stops, routes, trips, stop_times, calendar,
shapes, feed_info`); `calendar_dates.txt` absent in the feed (supported, tested synthetically). Also supported when present:
frequencies, transfers, levels, pathways, attributions, fare_attributes, fare_rules (synthetic tests only). VERIFIED.

## 3. Final database schema
17 GTFS tables + `import_meta`, `user_version = 2`. Full DDL: `backend/app/gtfs/schema.py`; explanation:
[GTFS_DATA_MODEL.md](GTFS_DATA_MODEL.md).

## 4. Final row counts (real Delhi feed) – VERIFIED
agency 2 · stops 6,812 · levels 0 · routes 2,554 · trips 65,322 · calendar 1 · calendar_dates 0 · shapes 2,554 ·
shape_points 765,633 · stop_times 2,385,381 · frequencies 0 · transfers 0 · pathways 0 · attributions 0 ·
fare_attributes 0 · fare_rules 0 · feed_info 2. Rows rejected: 0 in every file.

## 5. Validation errors and warnings – VERIFIED on the real feed
0 errors · 2 warnings · 15 info · integrity checks: 30 passed, 1 reported a finding, 15 skipped (empty optional tables).
Warnings: `feed_info_multiple_rows` (2 rows), `consecutive_duplicate_stop` (1,846). Info includes overnight service
(22,719 rows), extension `fare_stage` (stored, 2,385,381 rows populated) and `stop_dist` (empty), 1,957 stop names shared
by several stop_ids. Rules: [VALIDATION_RULES.md](VALIDATION_RULES.md).

## 6. Calendar behaviour – VERIFIED
`get_active_service_ids(conn, date)` / `evaluate_services`: weekly flag + inclusive range, then `calendar_dates` add/remove,
no assumption that `calendar_dates.txt` exists, trips are never assumed to run daily. Real feed: 1 service, 0 exceptions;
active on 2026-11-08 (Sun) and 2026-11-09 (Mon), inactive on 2024-12-31 and 2040-01-02. 13 deterministic unit tests
(weekday/weekend, added, removed, outside range, calendar_dates-only, trip-only service, reasons).

## 7. Shape processing – VERIFIED
765,633 points stored in sequence order; derived `shapes` table; 65,322/65,322 trips resolve to a shape; largest shape
1,501 points; 0 duplicate sequences, 0 decreasing distances, 0 invalid coordinates. Trip without shape → explicit
`shape_available: false` + reason + opt-in labelled stop-sequence fallback (synthetic test; Delhi has none).

## 8. APIs implemented – VERIFIED (tests + real DB smoke run)
All 11 requested endpoints plus `/stops/{id}/departures`, `/routes/{id}/trips`, `/routes/{id}/shapes`, `/shapes/{id}`.
Reference: [API.md](API.md).

## 9. Query performance – measured on the real DB
[PERFORMANCE.md](PERFORMANCE.md). Medians: stop by PK 0.00 ms; next 20 departures at busiest stop 0.03 ms; page of a
trip's stop_times 0.07 ms; full 1,501-point shape 0.81 ms; routes serving the busiest stop 9.4 ms; trips scan 8 ms.
No query scans `stop_times`/`shape_points` (asserted by the real-feed test). One honest regression: stop-detail at the
busiest stop got slower (≈4.6 → 7.6–9.4 ms) in exchange for a ~150× faster departures lookup.

## 10. Test execution results
* Backend default: **197 passed, 9 skipped** (the 9 are the opt-in real-feed tests). VERIFIED.
* Backend real feed (`-m real_feed`, temporary database): **9 passed**. VERIFIED.
* Frontend: **33 passed** (24 original untouched + 9 new). VERIFIED.
* Mutation spot-check: deliberately broke overnight handling and the calendar end-date; the suite failed as it should; reverted.
* Real-database safety: tests build their own databases; the real DB was never opened for writing (all real imports went to `/tmp`).

## 11. Frontend build – VERIFIED
`npm run build`: success (≈231 kB JS / 72.6 kB gzip).

## 12. Files created / modified
Created (22): `app/api/{gtfs,network}.py`, `app/gtfs/{calendar,spec}.py`, `app/services/{network,shape,summary,time}_service.py`,
`scripts/benchmark_queries.py`, 4 test modules (`gtfs_full.py`, `test_api_v1.py`, `test_calendar.py`,
`test_gtfs_phase1_import.py`), 5 docs, 4 frontend files (`NetworkSummary`, `StopDetails`, `useAsync`, `Phase1Panels.test`).
Modified (25): README, CHANGELOG, ARCHITECTURE, `verify.ps1`, requirements, importer/loader/archive/validation/schema,
schemas, main, deps, stops API/service, journey service (delegates to the calendar engine), import CLI, 4 existing
test files (fixtures + 2 intentional contract edits), `App.jsx`, `crowdsense.js`, `style.css`.

## 13. Known limitations
See the README section; main points: static schedule only; direct-trip routing only; Phase 0 journey search ignores
previous-day overnight trips; no interpolation of empty times; Fares v2/translations not imported; optional-file
parsers proven by synthetic data only; not a compliance certificate; DB ~286 MB; no map in the UI.

## 14. Windows PowerShell verification commands
```powershell
cd <repo>\backend
py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt                  # also installs tzdata on Windows
python -m pytest -q                                  # expect: 197 passed, 9 skipped
$env:CROWDSENSE_REAL_FEED_ZIP = "data\delhi_buses_static_gtfs_v1.zip"
python -m pytest -m real_feed -q                     # expect: 9 passed (temporary DB, ~30 s)
Remove-Item Env:CROWDSENSE_REAL_FEED_ZIP
python -m scripts.import_gtfs --validate-only        # database untouched
python -m scripts.import_gtfs                        # upgrades the v1 database; old one kept as *.previous
python -m scripts.benchmark_queries --markdown       # timings + query plans on your machine
python -m app                                        # API on http://127.0.0.1:8000  (docs at /docs)
# second terminal
Invoke-RestMethod http://127.0.0.1:8000/api/v1/gtfs/summary | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/services/active?date=2026-11-09"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/trips/1_06_05/shape?limit=3" | ConvertTo-Json -Depth 4
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/stops/115" | ConvertTo-Json -Depth 3
cd ..\frontend ; npm ci ; npm test ; npm run build  # expect: 33 passed, build ok
# everything at once
cd .. ; powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
```

## 15. Implemented and verified vs. not verified
**Verified here:** everything marked VERIFIED above, including the real-feed import (≈30 s), the v1→v2 upgrade on a copy
of your real Phase 0 database (core counts identical, previous file preserved), failed-import preservation (tests), all
endpoints against the real database.
**Not verified:** (a) nothing was run on **Windows** – paths, file-replace behaviour and `tzdata` installation are
unchanged-in-design from Phase 0 but unexercised here; (b) the UI was tested with jsdom + a production build, **not in a
real browser**; (c) no load/concurrency test and no peak-memory measurement; (d) frequencies/transfers/pathways/levels/
attributions/fares parsers run on synthetic data only (the Delhi feed has none); (e) timings are from this sandbox.
