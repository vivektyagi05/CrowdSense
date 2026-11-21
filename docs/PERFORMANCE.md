# Performance evidence

Everything below was measured on the **real Delhi database** (285,667,328 bytes; 2,385,381 stop_times) with
`python -m scripts.benchmark_queries --runs 50 --markdown` on a Linux sandbox (Python 3.12, SQLite 3.45), warm cache,
single connection. They are measurements for that machine and file, **not guarantees**. Re-run the script on your PC.
The benchmark picks its parameters from the data (busiest stop, largest shape, busiest route, longest trip).

| Query | median ms | p95 ms | rows |
|---|---:|---:|---:|
| stop name search (leading-wildcard LIKE) | 1.18 | 1.29 | 20 |
| stop by primary key | 0.00 | 0.01 | 1 |
| routes serving the busiest stop (4,192 stop_times, 139 routes) | 9.39 | 13.06 | 139 |
| next 20 departures at the busiest stop, after 08:00, one service | 0.03 | 0.04 | 20 |
| stop_times of the longest trip (page of 100) | 0.07 | 0.09 | 100 |
| trip by primary key | 0.00 | 0.00 | 1 |
| all points of the largest shape (1,501 points) | 0.81 | 1.06 | 1501 |
| trips of the busiest route + first departure (page of 50) | 0.11 | 0.15 | 50 |
| distinct stops of the busiest route | 0.13 | 0.15 | 1 |
| stops served by a route (`/stops?route_id=`) | 0.17 | 0.21 | 7 |
| trip count per service_id (full `trips` scan) | 8.01 | 8.43 | 1 |
| trips using one shape_id (full `trips` scan, no index) | 2.79 | 3.29 | 1 |
| Phase 0 direct-journey query (stop pair) | 0.25 | 0.29 | 10 |

Query plans (`EXPLAIN QUERY PLAN`, printed by the script): every lookup on `stop_times` or `shape_points` is a `SEARCH …
USING INDEX`. The only scans are `stops` (6.8k rows, name search), `calendar` (1 row) and `trips` (65k rows, in the two
aggregate queries above). **No query scans `stop_times` or `shape_points`.** The real-feed integration test asserts this
for four representative lookups.

HTTP-level: 21 single requests through the in-process test client on this database took about 4–17 ms each (the slowest
were the first calls, which include connection warm-up; `/gtfs/summary` and `/services/active` ≈ 15 ms because they
scan the 65k-row `trips` table once). This is not a load test: no concurrency or throughput claims are made.

## Index decisions (measured on a copy of the database)

| Candidate | Result | Decision |
|---|---|---|
| `stop_times(stop_id, departure_time)` **replacing** `idx_stoptimes_stop(stop_id)` | departures at the busiest stop **3.7 ms → 0.02 ms**; routes serving that stop **4.6 → 7.6 ms** (9.4 ms in the final run: noisier, same direction); database **+~23 MB** | **Adopted.** It still serves every `stop_id` lookup via its prefix (so nothing is redundant), and time-ordered "what leaves this stop after t" is the access pattern the routing phase needs. The trade-off is a slightly slower stop-detail query at very busy stops |
| keep both `(stop_id)` and `(stop_id, departure_time)` | redundant | rejected |
| `trips(shape_id)` | "trips using a shape" 2.3 ms → ~0 | **Rejected**: no endpoint asks that question; route→shape listings use `idx_trips_route_service` |
| `stop_times(stop_id, trip_id)` (Phase 0 benchmark) | not chosen by the planner | stays rejected |

Indexes are not a substitute for routing logic: the time index only makes *candidate lookup* cheap; correctness of
service days, midnight handling and transfers is the job of the next phase.

## Import cost

| | Phase 0 | Phase 1 |
|---|---|---|
| Wall time (real feed) | ~24 s | ~29–31 s |
| Files / tables | 5 / 6 | 8 / 17 |
| Database size | ~193 MB | ~286 MB (+shape_points 0.77 M rows, wider stop_times, wider index) |

Peak import memory was not measured; the design keeps only key sets of the small tables in memory and streams the two
large ones.

## Caching

None is used. The summary reads row counts from `import_meta` (written in the same transaction as the data, so it cannot
be stale for that file) and runs a few bounded queries. Response caching would need an invalidation hook on database
promotion; nothing measured so far justifies it.
