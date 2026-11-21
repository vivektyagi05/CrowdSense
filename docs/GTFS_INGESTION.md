# GTFS ingestion

```
python -m scripts.import_gtfs                  # build + validate + promote
python -m scripts.import_gtfs --validate-only  # everything except promotion; database untouched
python -m scripts.import_gtfs --json           # machine-readable report on stdout
```

The Phase 0 safety design is unchanged: **staging database → validate → atomic promote**, with `<db>.previous` kept and
automatic restore if post-promotion verification fails. A failed import never touches the served database.

## Pipeline

1. **Archive inspection** (`gtfs/archive.py`, no database): ZIP CRCs; decompression-size guard; locate the GTFS folder
   (ZIP root *or* one nested folder, as in `delhi_buses_static_gtfs_v1-2/`); require `stops`, `routes`, `trips`,
   `stop_times` and at least one of `calendar` / `calendar_dates`; validate the **header of every supported file that is
   present** (duplicate/empty column names, required columns). Classify the rest: optional files absent, GTFS files that
   are recognised but not imported, files that are not GTFS at all.
2. **Streaming load** (`gtfs/loader.py`): one table-driven parser per file generated from `gtfs/spec.py`. Rows are
   streamed from the ZIP and inserted in batches of 50,000. Only key sets of the small/medium tables are kept in memory
   (for duplicate detection); `stop_times` (2.4 M rows) and `shape_points` (0.77 M) never are.
   Every bad row becomes an error with **file, line and reason**; none is silently dropped. Per-file accounting:
   `rows_read = rows_imported + rows_rejected`.
3. **Duplicate-key check** (set-based SQL) for `(trip_id, stop_sequence)` and `(shape_id, shape_pt_sequence)`, then the
   UNIQUE indexes, the derived `shapes` summary, and the remaining indexes.
4. **Validation engine** (`gtfs/validation.py`): referential integrity, schedule consistency, calendar and shape checks,
   column usage, extension columns. Findings are `error` / `warning` / `info`; **any error aborts** the import. Rules:
   [VALIDATION_RULES.md](VALIDATION_RULES.md).
5. **Commit**, WAL checkpoint, `fsync`, `quick_check`, then **promotion** (unchanged from Phase 0).

Measured on the real Delhi feed (Linux sandbox, Python 3.12): **~29–31 s** end to end, resulting database **~286 MB**
(Phase 0: ~24 s, ~193 MB for 5 files and fewer columns). Your Windows timings will differ.

## What is imported, what is not

* Every column of every supported file is stored if it is part of the GTFS specification.
* **Extension columns**: `fare_stage` and `stop_dist` in `stop_times.txt` are not GTFS-standard. They are stored (they
  may matter for fares later) and reported as an *info* finding. `stop_dist` is empty in all 2,385,381 rows (reported).
* **Unknown columns** are never stored silently: they are listed in the report (`columns.unsupported`) and raise a
  warning (`unsupported_columns`).
* **Recognised GTFS files this phase does not import** (translations, Fares v2, areas, networks, location groups, booking
  rules, `locations.geojson`) raise `recognised_file_not_imported`. Files that are not GTFS raise `unrecognised_file`.
* Absent optional files are listed in `missing_optional_files`; their tables stay empty.

## Report

Two separate pieces of information are produced and deliberately kept apart:

| | Question it answers | Where |
|---|---|---|
| **Import status** | Did the last *attempt* work? (`success` / `failed`, phase, duration, errors) | `<db>.import-status.json`; `last_import_attempt` in the API |
| **Data quality** | What is true about the data *in the database being served*? | stored **inside** the database (`import_meta.import_report`), so it can never drift from the data; `GET /api/v1/gtfs/validation-report` |

A failed import changes the first and never the second.

Report contents (`ImportReport`, JSON): feed metadata, imported file list (`file_details`: rows read / imported /
rejected, standard / extension / unsupported columns per file), `table_counts` (all 17 tables) and `counts` (the six
Phase 0 tables, unchanged), `missing_optional_files`, `recognised_unimported_files`, `unrecognised_files`, `column_usage`
(non-NULL count of every column), `data_quality` (`status`, counts, `findings`, `integrity_checks` with passed / failed /
skipped for **every** check), warnings, errors, duration and `staging_build_seconds`, source SHA-256 and size.

`data_quality.status`: `pass` · `pass_with_warnings` · `fail` (a failed import is never promoted).

## Upgrading from a Phase 0 database

Existing databases have `PRAGMA user_version = 1`. They keep serving the Phase 0 endpoints, but every Phase 1 endpoint
answers `503 schema_outdated` ("Run: python -m scripts.import_gtfs"). Running the import builds a version-2 database and
promotes it; the Phase 0 file is kept as `<db>.previous`. This upgrade path was run against a copy of the real Phase 0
database: core counts identical before and after, previous database preserved.

## Re-running

Each import is a fresh build, so repeated imports can never duplicate rows (tested: three consecutive imports give the
same counts). The importer is serialised by `<db>.import.lock`.
