# Phase 4 — EVIDENCE

Every number below was produced by a command run in this session (2026-11-13, Linux, Python 3.12.3, Node 22.23.4, SQLite 3.45.1).
Anything not backed by a pasted command is labelled **UNVERIFIED**. Outputs are trimmed only where marked.

## M1.0 Baseline (before any Phase 4 change)

```
$ cd backend && python -m scripts.import_gtfs          # real Delhi GTFS -> data/crowdsense.sqlite3 (25.6 s)
Data quality: PASS_WITH_WARNINGS  (0 errors, 2 warnings, 15 info)
$ python -m pytest -q                                    # backend
197 passed, 9 skipped, 1 warning
$ cd ../frontend && npx vitest run                       # frontend
Tests 106 passed | 1 skipped (107)
$ npx vite build                                         # entry chunk baseline
dist/assets/index-BXhdegqC.js   326.35 kB | gzip: 104.13 kB
```
The 9 backend skips are `test_real_feed.py` (needs `CROWDSENSE_REAL_FEED_ZIP`); 1 frontend skip is `live.test.jsx` (needs a live backend). Both match the spec's 197 / 106 counts.

## M1.1 Database facts  (`backend/scripts/audit_m1_db.py`, read-only)
```
$ python scripts/audit_m1_db.py
== counts
stops 6812
routes 2554
trips 65322
stop_times 2385381
shapes 2554
shape_points 765633

== stops: coordinates
null coords: 0
zero coords: 0
lat/lon min/max: [(28.20808181741647, 29.341845864677428, 76.60075639009779, 77.43117)]
outside audit box (28.0, 29.1, 76.6, 77.8) : 12
outside strict Delhi bbox (28.40-28.90N,76.84-77.35E): 179
stops with no stop_times (no routes): 0
empty/null stop_name: 0
location_type values: [(None, 6812)]
parent_station non-null: 0

== names
distinct raw names: 4576  distinct normalised: 4353
normalised names shared by >1 stop: 2124  stops involved: 4583
name-group size histogram: [(1, 2229), (2, 1905), (3, 130), (4, 69), (5, 14), (6, 5), (7, 1)]
exact duplicate coordinates (pairs sharing lat/lon): 1

== cluster size histograms (same normalised name + complete linkage), by threshold
  50 m: clusters=5103 multi-stop=1702 hist=[(1, 3401), (2, 1695), (3, 7)]
 100 m: clusters=4776 multi-stop=2006 hist=[(1, 2770), (2, 1980), (3, 22), (4, 4)]
 150 m: clusters=4674 multi-stop=2078 hist=[(1, 2596), (2, 2027), (3, 42), (4, 9)]
 250 m: clusters=4577 multi-stop=2100 hist=[(1, 2477), (2, 2001), (3, 68), (4, 27), (5, 3), (6, 1)]
 400 m: clusters=4517 multi-stop=2112 hist=[(1, 2405), (2, 1980), (3, 86), (4, 42), (5, 3), (6, 1)]

== pairwise-distance distribution inside same-name groups (nearest neighbour per stop, m)
n= 4583 p10 13.6 p25 18.4 p50 27.8 p75 50.9 p90 120.3 p95 268.6
nearest-same-name distance bins: {'0-25': 2047, '25-50': 1370, '50-75': 431, '75-100': 200, '100-150': 182, '150-200': 77, '200-250': 36, '250-400': 74, '400-800': 86, '800-1600': 45, '1600-5000': 6, '5000-1000000000.0': 29}

== shapes
shapes with <2 points: 0
point_count column vs actual mismatch: 0
trips total / with shape_id null: 65322 0
trips whose shape_id not in shapes: 0
distinct shapes used by trips: 2554
shapes unused by any trip: 0
shape points with dist_traveled NOT NULL: 765633 of 765633
max point_count / avg point_count: [(1501, 299.8)]
stop_times shape_dist_traveled NOT NULL: 0
stop_times stop_dist NOT NULL (non-GTFS col): 0
shapes whose rowid order != sequence order: 0
shapes with decreasing shape_dist_traveled (in sequence order): 0
shapes with decreasing shape_dist_traveled by sequence order: 0
shapes with all-null shape_dist_traveled: 0

== trips / stop_times
trips with <2 stop_times: 0
trips with duplicate stop (loop/repeat) : 2697
routes with >1 distinct shape: 0
headsign null/empty trips: 65322
direction_id values: [(None, 65322)]
stop_headsign non-null in stop_times: 0
```

### What these numbers decided
| Finding | Consequence |
|---|---|
| `stop_times.shape_dist_traveled` is NULL in **2,385,381 / 2,385,381** rows (shape_points have it in 765,633 / 765,633) | The spec's "use shape_dist_traveled if present" branch can never fire for this feed. Stop->shape mapping is **always projection**. The distance branch is still implemented and tested (synthetic) but is dead for Delhi data. |
| `trip_headsign` empty for **65,322 / 65,322** trips, `stop_headsign` empty everywhere, `direction_id` NULL | "Towards X" headsigns **do not exist** in this feed. Per spec rule, no "towards" label is invented. Cluster members are distinguished by routes, coordinates, bearing and call counts only. Route names (e.g. `102ADOWN`) are real data and are shown as route names, not as headsigns. |
| Exactly 1 shape per route, 1 distinct stop sequence per route (2,554 / 2,554) | Every route is a single direction pattern. Projection has one canonical polyline per route; shape selector (M8) will legitimately have a single option for all 2,554 routes. |
| 2,697 trips repeat a stop (loops; longest trip `2716_04_50` starts and ends at ISBT Anand Vihar, 183 calls, 1,501 shape points) | Loop handling is mandatory, and a real golden test case exists. |
| 1,846 consecutive duplicate stop_times (importer warning) | Projection must tolerate repeated adjacent stops (same projection index allowed: `>=`). |
| 12 stops outside (28.0–29.1 N, 76.6–77.8 E); stop extent is lat 28.208–29.341, lon 76.601–77.431; 179 stops outside strict Delhi box | NCR box for validation = **28.00–29.50 N, 76.40–77.80 E** (contains all 6,812 stops, verified in M4). |
| Same-name nearest-neighbour distance p50 27.8 m, p90 120.3 m, p95 268.6 m; 88 % of same-name stops have a twin within 100 m | Cluster threshold candidates in M5 ADR. Multi-stop clusters: 1702 (50 m) -> 2006 (100) -> 2078 (150) -> 2100 (250) -> 2112 (400): the curve flattens after 150 m. |
| Shape defects: 0 shapes <2 pts, 0 unordered, 0 non-monotone dist, 0 trips without shape | Real data is clean; defect handling is proven with **synthetic** fixtures, labelled as such. |
| 0 stops without routes; 0 null/zero coordinates | No orphan-stop handling needed beyond defensive checks. |

## M1.2 Existing endpoints: size and latency (`backend/scripts/audit_m1_latency.py`, 127.0.0.1, uvicorn, n=30)
```
$ python -m app &  ;  python scripts/audit_m1_latency.py
longest: ('2716', '2716_04_50', 'shp_3_883', 1501)  typical: ('1067', '1067_07_45', 'shp_3_894', 285)
GET /trips/{id}/shape [longest, 1501 pts]    status=200 bytes=  112797 gzip=  21678 p50=   6.4ms p95=  25.7ms n=30
GET /trips/{id}/shape?format=geojson [longest] status=200 bytes=   33213 gzip=   9423 p50=   5.7ms p95=  23.9ms n=30
GET /routes/{id}/shapes [longest]            status=200 bytes=      89 gzip=     96 p50=   1.6ms p95=   1.9ms n=30
GET /shapes/{id} [longest]                   status=200 bytes=  112789 gzip=  21665 p50=   6.3ms p95=  12.3ms n=30
GET /trips/{id}/shape [typical, 285 pts]     status=200 bytes=   21320 gzip=   4314 p50=   2.6ms p95=   5.5ms n=30
GET /trips/{id}/shape?format=geojson [typical] status=200 bytes=    6703 gzip=   1986 p50=   2.6ms p95=   4.3ms n=30
GET /routes/{id}/shapes [typical]            status=200 bytes=      88 gzip=     94 p50=   1.6ms p95=   1.9ms n=30
GET /shapes/{id} [typical]                   status=200 bytes=   21312 gzip=   4304 p50=   2.6ms p95=   2.8ms n=30
GET /stops/{id} (detail)                     status=200 bytes=    1209 gzip=    380 p50=   2.3ms p95=   2.6ms n=30
GET /stops?q= (100 mixed substring queries)   p50=4.1ms p95=4.5ms max=6.3ms
sample query/total/size: [('n As', 6), ('Blo', 353), ('Vi', 1154), ('hup', 6), ('ema', 72)]
current search 'kashmire gate'      -> total=0
current search 'kashmere gate'      -> total=11
current search 'Kashmere  Gate'     -> total=0
current search 'कश्मीरी गेट'        -> total=0
current search 'gate kashmere'      -> total=0
```
Notes: (a) `/routes/{id}/shapes` returns shape *references only* (no geometry): the spec's "same simplification" requirement is therefore an additive extension. (b) Responses are **not compressed** by the server today (no GZip middleware); "gzip" column is `gzip.compress` of the body, i.e. what a compressing proxy would send. (c) The existing `GET /trips/{id}/shape` has `fallback=stops`, which returns the stop-sequence polyline (labelled `stop_sequence_fallback`). That polyline is a straight-line path between stops: Phase 4 frontend must **never** request or draw it (Integrity rule 2).

## M1.3 Search plan
```
select ... where lower(stop_name) like lower('%gate%') escape '\' order by stop_name, stop_id limit 20
   SCAN stops
   USE TEMP B-TREE FOR ORDER BY
select stop_id from stops where stop_lat between 28.6 and 28.7 and stop_lon between 77.2 and 77.3
   SCAN stops
```
Substring search = full scan of 6,812 rows (p95 4.5 ms: fast enough, but no ranking, no typo tolerance, no token reorder). Current behaviour on real queries: `kashmere gate` -> 11, `kashmire gate` -> **0**, `Kashmere  Gate` (double space) -> **0**, `gate kashmere` -> **0**, Devanagari -> 0. A bbox query is also a full scan: no spatial index exists.

## M1.4 Indexes, SQLite modules, CORS, privacy
```
Indexes: idx_stoptimes_trip_seq (trip_id, stop_sequence) UNIQUE; idx_shape_points_seq (shape_id, shape_pt_sequence) UNIQUE;
         idx_stoptimes_stop_dep (stop_id, departure_time); idx_trips_route_service (route_id, service_id); idx_calendar_dates
         (no index on stops(stop_name) or stops(lat,lon))
SQLite 3.45.1 ; compile options include: ENABLE_FTS3, ENABLE_FTS3_PARENTHESIS, ENABLE_FTS3_TOKENIZER, ENABLE_FTS4, ENABLE_FTS5, ENABLE_RTREE
```
=> R-tree and FTS5 are available **in this environment**. (A user's Windows Python bundles its own SQLite: availability there is checked at build time by the build script and falls back, see M4/M5 ADR.)

CORS: `CORS_ALLOWED_ORIGINS` default `http://localhost:5173, http://127.0.0.1:5173`; GET/OPTIONS only; no credentials. Vite dev+preview use `strictPort: 5173`.

**Privacy finding (must fix in M4):** uvicorn's default access log prints full query strings:
```
$ grep "stops?q=" /tmp/server.log
INFO:     127.0.0.1:57310 - "GET /api/v1/stops?q=n+As&limit=20 HTTP/1.1" 200 OK
```
`python -m app` therefore **would log `lat=`/`lon=`** of `/stops/nearby`. Integrity rule 5 requires this to be closed and proven.

`src/lib/geo.js` public surface: `toMapStops(stopTimes)`, `legGeometryRef(leg)`, `transferPoints(journey)` (3 pure helpers; no map code, no projection, no bounds).

## M1.5 Implementation matrix
| Capability | Actual status | Evidence | Action |
|---|---|---|---|
| Place search (P1) | Substring only; typo/reorder/space/Devanagari = 0 results | M1.3 | M6 smart search |
| Same-name clusters (P2) | None; 2,124 normalised names shared by >1 stop (4,583 stops) | M1.1 | M5 clusters @ threshold from ADR |
| Route geometry (P3) | Raw full shape (1,501 pts, 112 KB / 21.7 KB gz); no leg slicing; no simplification; `fallback=stops` straight-line option exists | M1.2 | M3 leg endpoint; frontend never uses fallback |
| Nearby / spatial index (P4) | None; bbox filter is full scan | M1.3 | M4 R-tree |
| Saved places (P5) | None | n/a | M10 localStorage v1 |
| Map engine in frontend | None (`geo.js` only 3 pure helpers) | M1.4 | M7 |
| `shape_dist_traveled` per stop_time | **Absent** (0 / 2,385,381) | M1.1 | projection-only for this feed |
| Headsigns | **Absent** (0 / 65,322) | M1.1 | no "towards" labels |
| Access-log privacy | **Leaks query strings** | M1.4 | M4 fix + test |
| R-tree / FTS5 | Present (3.45.1) | M1.4 | use, with fallback + runtime detection |


---
# Milestones 2–13 (all outputs below were produced in this session; commands shown)

## M2 Platform facts
```
$ npm view maplibre-gl time        # newest versions
6.16.0 2026-10-25 (20 d old at audit)   6.17.0 2026-11-07 (6 d: too new)   6.18.0 (too new)
$ npm view @maplibre/geojson-vt time        -> range ^6.3.0 resolved 6.3.1 = 3 days old  => overridden to 6.3.0 (29 d)
$ npm view @maplibre/maplibre-gl-style-spec -> range ^26.4.4 resolved 26.7.0 = 0 days old => overridden to 26.4.4 (60 d)
$ PyPI hypothesis: 6.170.13 uploaded 2026-10-28 (17 d), licence MPL-2.0
$ web_search + fetch: OpenStreetMap Foundation tile usage policy (operations.osmfoundation.org/policies/tiles): no heavy/production use, may be blocked, attribution required
```
Dependency closure of `maplibre-gl` (25 packages, youngest 20 d, licences BSD-3-Clause / ISC / BSD-2-Clause / MIT / MIT-OR-Apache-2.0): see the table in `DECISIONS.md` ADR-03.

## M3 Backend: leg geometry
Projection threshold derivation (`python -m scripts.audit_m3_projection`, one trip per route, all 2,554 routes):
```
routes=2554 stop-calls=86326 matched<=500m=86326 unmatched(>500m)=0
distance stop->matched shape point (m): p50 2.3 p90 9.3 p95 12.2 p99 29.3 p99.9 93.8 max 189.1
  share of stop-calls within  20 m: 98.07%
  share of stop-calls within  30 m: 99.02%
  share of stop-calls within  40 m: 99.37%
  share of stop-calls within  60 m: 99.66%
  share of stop-calls within  80 m: 99.83%
  share of stop-calls within 100 m: 99.92%
  share of stop-calls within 150 m: 100.00%
routes whose matched positions are not monotone: 0
routes with any stop >500 m from shape: 0
worst 5 routes (max matched distance m): [(189.1076350421679, '2931'), (152.97591329284867, '1472'), (141.49542457899278, '1444'), (136.66539905351024, '1397'), (136.62189013107704, '3124')]
projection time per full trip (ms): p50 2.8 p95 6.0 max 26.1
```
Gate run against the live server (`python -m scripts.audit_m3_gate`, uvicorn on 127.0.0.1):
```
[longest route 2716] full loop (183 calls): status=ok orig_pts=1319 returned=412 len=106522.6m (orig 106609.5m) bytes=9391 gzip=3233 | p50=12.0ms p95=26.0ms (n=30) | legacy full shape bytes=112797 gzip=21678
[longest route 2716] mid leg 40->120: status=ok orig_pts=541 returned=154 len=41461.1m (orig 41492.0m) bytes=3771 gzip=1374 | p50=9.1ms p95=24.9ms (n=30) | legacy full shape bytes=112797 gzip=21678
[300 random legs, all routes] statuses={'ok': 288, 'unreliable_projection': 5} p50=3.6ms p95=5.2ms p99=7.0ms max=10.8ms
   simplified/original length ratio: min=0.9940 max=1.0000; mean leg payload=981 bytes
[all 2,554 shapes @5 m] points 765,633 -> 222,064 (29.0%); max length loss 0.676%; max deviation (shapes<400 pts) 5.000 m
[routes/2716/shapes?geometry=true&tolerance_m=5] pts 1501->413 bytes=9234 gzip=3138 p50=6.9ms p95=9.5ms
[routes/2716/shapes?geometry=true&tolerance_m=20] pts 1501->185 bytes=4266 gzip=1585 p50=6.2ms p95=9.2ms
```
| Gate | Budget | Measured |
|---|---|---|
| leg endpoint p95, longest route (whole 183-call loop) | < 120 ms | **26.0 ms** (p50 12.0) |
| payload, longest route leg | ≤ 40 kB gzip | **3,233 B gzip** (9,391 B raw; legacy full shape 21,678 B gzip / 112,797 B raw) |
| point reduction | report | 1,319 → 412 points (leg); 765,633 → 222,064 over all shapes at 5 m (29.0 %) |
| max deviation of simplified from original | ≤ tolerance | **5.000 m** at 5 m over all 2,554 shapes < 400 pts (exact), Hypothesis for the rest |
| length within 1 % | ≤ 1 % | max loss **0.676 %** (all shapes); legs ratio min 0.9940 |
| outcomes on 293 random real legs | report | ok 288, unreliable_projection 5 (1.7 %), no_shape 0 |

Tests: `test_leg_geometry.py` (22, SYNTHETIC road world, `tests/geo_world.py`: straight road, rectangle loop, out-and-back on one road, off-road stop, valid/inconsistent-unit shape_dist, no shape, stop not on trip, alight-before-board, tolerance clamp, board-time forms, legacy endpoint unchanged), `test_planar_properties.py` (8 Hypothesis properties, 300 examples each), `test_real_leg_golden.py` (5, REAL DB: loop 106,522.6 m ±1 %, mid leg 41,461.1 m ±1 %, stop-not-on-trip, documents that no-shape/shape_dist cases are absent from real data, 256 real routes monotone).
A **real defect found and fixed** while writing these: adding fields to `RouteShapeRef` leaked `null`s into `/routes/{id}` and broke an existing exact-match test; fixed in code with a separate `RouteShapeGeometry` subclass (test untouched).

## M4 Backend: nearby + spatial index + privacy
Gate (`python -m scripts.audit_m4_gate <db>` against a live server on the derived-built real DB):
```
index method: rtree
all stops inside NCR box: True
oracle: 200/200 identical (set + order); non-empty results in 113/200
latency (500 req, radius 500, limit 20): p50=2.3ms p95=3.1ms p99=3.8ms max=4.6ms
latency worst-case params (100 req, radius 3000, limit 50): p50=3.6ms p95=5.2ms max=5.6ms
```
Server log after those ~800 requests: `GET /api/v1/stops/nearby?lat=[redacted]&lon=[redacted]&radius_m=1000&limit=1 HTTP/1.1 200 OK`; programmatic grep of 200 probe coordinates (9-char prefixes of each lat and lon) against the log: **coordinate leaks: 0**; nearby requests logged 800, `[redacted]` markers 1600.
**Mutation check** of the privacy test: with `install_privacy_filters()` disabled, `test_real_server_logs_contain_no_coordinates` fails; with it enabled it passes (so the test can actually detect a leak).
Tests: `test_nearby.py` (56 tests): oracle on 200 random points × 3 index paths (rtree, grid, scan) on 2,500 SYNTHETIC stops, validation matrix, defaults, box edges, build idempotence + atomicity, redaction unit test, real-subprocess log test.

## M5 Backend: place clusters
Build twice on one file and once on an independent copy: identical `content_hash` `5e60fa2baadaaebeda97c75b6f2f5720367ffecdc7b4ae514d69519b889becd6`; a clean clone (fresh import) produced the same hash.
```
{'cluster_rule': 'same normalised name + complete linkage', 'cluster_threshold_m': '150.0', 'cluster_count': '4673', 'stop_count': '6812', 'content_hash': '5e60fa2baadaaebeda97c75b6f2f5720367ffecdc7b4ae514d69519b889becd6', 'headsigns_available': 'false'}
clusters: 4673 | size histogram: [(1, 2590), (2, 2036), (3, 38), (4, 9)] | stops in multi-stop clusters: 4222
every stop in exactly one cluster: (6812, 6812) of 6812

Largest 10 clusters (by members, then spread):
  c_1f7dd6c01699 'KISHAN GANJ DISPENSARY' n=4 max-pairwise=147m members=['10035', '10050', '7856', '7857']
  c_09b66663ed85 'Metal Forging' n=4 max-pairwise=144m members=['3754', '5021', '626', '8138']
  c_5dfdd92f75b7 'Dwarka International School' n=4 max-pairwise=144m members=['9643', '9655', '9674', '9681']
  c_b7e8ada213dc 'Hari Nagar Depot' n=4 max-pairwise=130m members=['1881', '1893', '4019', '4063']
  c_c5eb7ea588ec 'Khera More / Ghuman Hera Crossing' n=4 max-pairwise=106m members=['3380', '3569', '8056', '8092']
  c_465c7d6aa21a 'Rithala Metro Station' n=4 max-pairwise=95m members=['15', '4708', '4709', '83']
  c_9a15b3d4810a 'CREATIVE HEIGHTS LIG FLATS GATE 3' n=4 max-pairwise=76m members=['10341', '10342', '1857', '7837']
  c_b3860af14c45 'Dichau Chowk' n=4 max-pairwise=62m members=['3248', '4053', '4311', '9926']
  c_3a32e4aba488 'JhulJhuli Check Post / Ghumanhera Crossing' n=4 max-pairwise=57m members=['3572', '3599', '4172', '4173']
  c_4ef609a59cb0 'Kailash Colony Metro Station' n=3 max-pairwise=146m members=['6874', '8353', '8354']

20 random multi-stop clusters (seed 5):
  c_81c5dbbf0bff 'Saket A block(Malviya Nagar Metro Station)' n=2 spread=30m | 2906:MS-3UP,448DOWN,OMS(+)UP,534AUP | 2957:534DOWN,448UP,OMS(-)DOWN,428DOWN
  c_b5cf06565700 'Hindon Regulator(BRD)' n=2 spread=68m | 5885:492DOWN,347DOWN,443DOWN,355DOWN | 8501:347UP,492UP,443UP,355UP
  c_0e21766a33cc 'Hamidpur Village' n=2 spread=14m | 5377:138DOWN,138STLDOWN | 5379:138UP,138STLUP
  c_e9df98b7d001 'Samudaya Bhawan Khichripur Village' n=2 spread=20m | 2575:319ADOWN | 2578:319UP,319AUP
  c_7e65253607de 'Dhaka Village' n=3 spread=92m | 330:192DOWN,143DOWN,61DOWN,162DOWN | 383:192UP,971STL-BBM-1UP,61UP,143AUP | 9417:333DOWN,333UP
  c_1a471a6a8116 'Singhu Border Crossing' n=2 spread=15m | 1008:131DOWN,131UP,131ADOWN2,193ADOWN | 1011:131AUP2
  c_4f33bba80126 'Rajpur Crossing' n=2 spread=43m | 2866:523DOWN,523ADOWN,D-046DOWN,434DOWN | 2884:523AUP,523UP,D-046UP,434UP
  c_3a8a3361e3b9 'Sikandarpur' n=2 spread=78m | 7009:GURGAON TO BADARPUR BORDER DOWN | 7012:BADARPUR BORDER TO GURGAON UP
  c_bc6dd9f6f004 'Hargovind Enclave' n=2 spread=21m | 2104:473DOWN,39ADOWN,202AUP,375UP | 7876:473UP,39AUP,202ADOWN,267DOWN
  c_eb8d40882417 'Ram Jas Road' n=2 spread=35m | 4102:926DOWN,954DOWN,922DOWN,817NDOWN | 4112:926UP,922UP,954UP,817NUP
  c_7d3ce71bbb08 'Siri Fort Road' n=2 spread=85m | 2747:0419(NS)DOWN,522UP,544DOWN,419DOWN | 7954:0419(NS)UP,544UP,522DOWN,419UP
  c_c09acb67fa46 'Delhi University / North Campus' n=2 spread=24m | 4370:212DOWN,D-0002(-)DOWN,109UP,212ADOWN | 4376:212UP,D-002(+)UP,109DOWN,913UP
  c_3584868d2c52 'Friends Enclave Mundka' n=2 spread=30m | 132:567ASTLDOWN2,849STLDOWN,979AUP,979UP | 135:567ASTLUP2,849STLUP,979ADOWN,979DOWN
  c_7e6ca5da626e 'Hasanpur Village' n=2 spread=48m | 1153:73DOWN,GL-23UP,85DOWN,211UP | 7742:73UP,85UP,976UP,D-006UP
  c_06e1a267a73e 'CPWD Colony Vasant Vihar' n=2 spread=31m | 3513:623DOWN,D-010DOWN,D-7101UP,ANDHERIA BAGH MORE / CHHATARPUR METRO STATION - VASANT VIHAR METRO STATION DOWN | 3523:623UP,D-010UP,D-7101DOWN,VASANT VIHAR METRO STATION - ANDHERIA BAGH MORE / CHHATARPUR METRO STATION  UP
  c_6c205d1ed414 'Nangloi (Najafgarh Road)' n=2 spread=45m | 165:978UP,539DOWN,922UP,567STL-GHD-IUP | 1997:978DOWN,708DOWN,539UP,567BSTLDOWN
  c_cda8d26a1680 'Desh Bandhu Apartments' n=2 spread=29m | 3068:449DOWN,U-SPL-16DOWN | 6113:445DOWN,445UP,449UP,U-SPL-16UP
  c_8fa514b3390b 'Punjabi Bagh Market / West Punjabi Bagh' n=2 spread=22m | 3341:910DOWN,567BDOWN2,567DOWN,567ADOWN | 3351:910UP,567UP,567BUP2,567AUP
  c_5a5706ab7dea 'Mundhela Khurd Village' n=2 spread=10m | 4219:836DOWN,836LNKSTLDOWN | 4228:836UP,836LNKSTLUP
  c_c5eb7ea588ec 'Khera More / Ghuman Hera Crossing' n=4 spread=106m | 3380:628STLUP,825ALINKSTLDOWN,817UP,827UP | 3569:546STL-GHD-IIUP,567STL-GHD-IUP,926ASTL-GHD-IUP,D-9910UP | 8056:628LSTLDOWN,546STL-GHD-IIDOWN,567BSTLDOWN,926STL-GHD-IDOWN | 8092:628LSTLUP,DW-3STL-GHD-IDOWN,AIRPORT-08UP,GL-91STL-GHD-IIUP

multi-stop clusters with spread > 120 m (review list): 64
multi-stop clusters whose first/last member share none of their top-4 routes (typical for opposite sides): 2065 of 2083
```
Tests: `test_clusters.py` (17 tests: merge ≤150 m incl. inclusive boundary, no-merge >150 m, complete-linkage no-chaining, order independence ×20 shuffles, stable ids, suffix variants not merged, cosmetic spellings merged, nameless stops never merge, endpoint contract, 404/503, additive/omitted `cluster_id`, headsigns only when the feed has them).

## M6 Backend: smart search
```
first request after startup (index pre-warmed by lifespan): 19.1 ms
smart search, 200 queries: p50=21.7ms p95=52.7ms p99=82.7ms max=94.3ms
existing substring mode, same 100 queries: p50=5.8ms p95=9.0ms
response bytes (kashmere gate, limit 20): 9226
```
| Gate | Budget | Measured |
|---|---|---|
| relevance cases on real data | ≥ 40 | **118** parametrized cases (16 real names × exact/upper/spacing/punct/typo/transposition/reorder/prefix) + 7 targeted tests = 125 tests in `test_search_relevance.py`, expectations from independent SQL |
| p95 over 200 queries | < 150 ms | **52.7 ms** (p50 21.7, p99 82.7, max 94.3) after optimising fuzzy expansion (first version: p95 81.2 ms) |
| existing substring search | no regression | p95 9.0 ms; all pre-existing search tests pass unmodified |
The relevance file **failed 15 of its 125 tests on its first run** (typos ranked below partial matches; one over-ambitious prefix expectation). The ranking was changed (ADR-07) and the prefix assertion rewritten to test completeness; no case was removed.

## M7–M10 Frontend (jsdom, recorded fixtures, one live run)
New/extended test files (counts from `npx vitest run`): `lib/geo.test.js` 18 · `features/map/MapView.test.jsx` 16 · `features/map/mapAdapter.test.js` 14 (mock MapLibre) · `pages/JourneyDetailMap.test.jsx` 7 · `pages/RouteStopMaps.test.jsx` 11 · `pages/NearbyPage.test.jsx` 17 · `features/search/StopAutocompleteClusters.test.jsx` 8 · `features/places/places.test.jsx` 18 · `a11y.phase4.test.jsx` 7 · `live.phase4.test.jsx` 3 (live, needs backend).
**A real bug only the production build found:** MapLibre 6 has no default export; my adapter's `import maplibregl from` passed all 29 unit tests (the mock had mirrored my wrong assumption) and failed `vite build` with `MISSING_EXPORT`. Fixed (`import * as`), and the mock now exposes named exports only.

## M11 Contrast (computed from `tokens.css` values after resolving `var()` aliases; WCAG 2.x relative luminance)
```
pair                                                          ratio  need  kind      result
map notice text (--blue-700 on --blue-50)                     7.49  4.5   text      PASS
map warning / geometry note (--amber-700 on --amber-50)       6.52  4.5   text      PASS
map control text (--text on --surface)                       16.78  4.5   text      PASS
muted text on surface (--text-muted on --surface)             7.26  4.5   text      PASS
muted text on sunken (--text-muted on --surface-sunken)       6.89  4.5   text      PASS
active timeline row (--text on --emerald-50)                 15.01  4.5   text      PASS
active place row (--text on --emerald-50)                    15.01  4.5   text      PASS
combobox group heading (--text on --surface-sunken)          15.93  4.5   text      PASS
'similar spelling' tag (--amber-700 on --amber-50)            6.52  4.5   text      PASS
control border (--border-strong on --surface)                 1.51  3.0   non-text  FAIL
map marker board #146c2e vs white halo                        6.53  3.0   non-text  PASS
map marker alight #b3261e vs white halo                       6.54  3.0   non-text  PASS
map marker current #b45309 vs white halo                      5.02  3.0   non-text  PASS
map marker sibling #0e7490 vs white halo                      5.36  3.0   non-text  PASS
map marker stop/line #1f4e8c vs white halo                    8.31  3.0   non-text  PASS
map marker user #6d28d9 vs white halo                         7.10  3.0   non-text  PASS
route line #1f4e8c vs blank basemap #e9edf1                   7.06  3.0   non-text  PASS
board marker #146c2e vs blank basemap #e9edf1                 5.55  3.0   non-text  PASS
alight marker #b3261e vs blank basemap #e9edf1                5.56  3.0   non-text  PASS
current marker #b45309 vs blank basemap #e9edf1               4.27  3.0   non-text  PASS
sibling marker #0e7490 vs blank basemap #e9edf1               4.55  3.0   non-text  PASS
selected ring #111827 vs blank basemap #e9edf1               15.08  3.0   non-text  PASS
failures: 1
```
The single FAIL is the pre-existing Phase 3 token `--border-strong` (1.51:1 on white). All **new** Phase 4 controls were switched to `--ink-500` (4.97:1 on white, 4.22:1 on the blank-map background): `--control-edge`. Remaining `--border-strong` uses in Phase 4 CSS are decorative (dashed card outline, sheet grab bar, legend swatch outline), not control boundaries. Rendered contrast on a real basemap is UNVERIFIED (G1).

## M12 Test inventory and regression proof
```
$ cd backend && python -m pytest -q            -> 481 passed, 9 skipped      (Phase 3: 197 passed, 9 skipped)
$ cd frontend && npx vitest run                -> 222 passed, 4 skipped      (Phase 3: 106 passed, 1 skipped)
$ CROWDSENSE_LIVE_API=http://127.0.0.1:8000/api/v1 npx vitest run src/live.test.jsx src/live.phase4.test.jsx
   -> 4 passed (Phase 3 live test + 3 Phase 4 live tests against the real backend and real Delhi data)
```
Skips: 9 backend = `test_real_feed.py` (needs `CROWDSENSE_REAL_FEED_ZIP`, unchanged); frontend 4 = `live.test.jsx` (1) + `live.phase4.test.jsx` (3) when no backend env var is set.
Byte comparison of every pre-existing test/fixture/helper against `CrowdSense_Phase3_Frontend.zip`: all **identical** except `frontend/src/test/setup.js` (ADR-14: clears device-local storage between tests; no assertion changed). Backend: no original test file has fewer test functions than before. New backend test files: `test_leg_geometry`, `test_planar_properties`, `test_real_leg_golden`, `test_nearby`, `test_clusters`, `test_search_relevance`, `test_search_unit`.
The live test drives: search `rithla metro` (typo) → grouped place with its 4 real stops → `/clusters/{id}` agrees member by member and has no headsigns → journey details page requests `/trips/72_06_40/shape?from_stop_id=106&to_stop_id=216&board=06:56:26` (no `fallback`) and gets `status: ok`, `data_basis: gtfs_shape`, > 2 coordinates, boarding/alighting < 60 m from the shape → page shows "Path drawn from the published GTFS shape" and the (WebGL-less jsdom) "Map unavailable" card still lists the stops.

## M13 Production build (`npx vite build`, clean clone and working tree identical)
```
dist/assets/index-*.js            319.10 kB │ gzip: 101.82 kB   (baseline 326.35 / 104.13  => -2.31 kB gzip, budget +2 kB)
dist/assets/index-*.css            25.77 kB │ gzip:   5.58 kB
dist/assets/mapAdapter-*.js     1,060.03 kB │ gzip: 288.22 kB   (MapLibre; loaded only when a map renders AND WebGL exists)
dist/assets/mapAdapter-*.css       71.33 kB │ gzip:  10.25 kB
dist/assets/MapView-*.js            4.46 kB │ gzip:   1.83 kB      LazyMapView 0.67 kB │ 0.43 · BottomSheet 1.56 │ 0.80
dist/assets/StopAround-*.js         4.38 kB │ gzip:   1.65 kB      NearbyPage 7.19 │ 2.94 · JourneyDetailPage 9.02 │ 3.31 · RouteDetailPage 8.07 │ 2.82
$ grep -c 'import"./mapAdapter\|from"./mapAdapter' dist/assets/index-*.js   ->  0   (entry never statically imports the engine)
$ grep -l mapAdapter- dist/assets/*.js                                       ->  only MapView-*.js, via dynamic import()
index.html modulepreload: only jsx-runtime (shared React runtime), no map chunk.
```
Clean clone (`/tmp/clean`, fresh venv + `npm ci`): `import_gtfs` → `build_derived` (same hash) → pytest 481 passed → server `/health` ok → `/stops/nearby` log line shows `lat=[redacted]&lon=[redacted]` → vitest 222 passed → build green.

## Self-audit (spec §18) — raw output
```
### AUDIT 1: any code path drawing a straight line between stops as a route?
-- every place a LineString / line source is built (frontend src, non-test):
frontend/src/lib/geo.js:47:/** GeoJSON LineString feature from API geometry. Returns null unless there are >= 2 real points: never a guess. */
frontend/src/lib/geo.js:48:export function lineFeature(coordinates, properties = {}) {
frontend/src/lib/geo.js:50:  return pts.length >= 2 ? { type: 'Feature', properties, geometry: { type: 'LineString', coordinates: pts } } : null;
frontend/src/lib/geo.js:80:  const line = ok ? lineFeature(shape.coordinates, { source: 'gtfs_shape' }) : null;
frontend/src/lib/geo.js:91:  const line = ok ? lineFeature(shapeItem.coordinates, { source: 'gtfs_shape' }) : null;
-- any use of the backend's straight-line stop fallback (fallback=stops)?
frontend/src/api/endpoints.js:64: * The real GTFS shape between two stops of a trip (backend slices + simplifies it). Never passes `fallback=stops`:
frontend/src/pages/RouteDetailPage.jsx:130:  const fallback = useMemo(() => stops.map((s) => ({ id: `${s.id}-${s.sequence}`, name: s.name, href: `/stops/${encodeURIComponent(s.id)}` })), [stops]);
frontend/src/pages/JourneyDetailPage.jsx:83:  const fallbackStops = useMemo(() => leg.stops.map((s) => ({ id: `${s.id}-${s.sequence}`, name: s.name, href: `/stops/${encodeURIComponent(s.id)}` })), [le…
-- tests asserting it is never requested:
frontend/src/live.phase4.test.jsx:48:    expect(call.url.searchParams.get('from_stop_id')).toBe('106'); expect(call.url.searchParams.get('fallback')).toBeNull();
frontend/src/pages/JourneyDetailMap.test.jsx:31:    expect(call.searchParams.get('fallback')).toBeNull();                          // never the straight-line stop fallback

### AUDIT 2: any path showing crowd / live / ETA / occupancy values? (Phase 4 files only)
(no matches in any Phase 4 source file)
-- user-visible crowd strings on the journey page still the Phase 3 constants:
frontend/src/lib/crowd.js:16:export const CROWD_UNAVAILABLE_TITLE = 'Historical crowd data unavailable.';
frontend/src/lib/crowd.js:17:export const CROWD_UNAVAILABLE_DETAIL = 'ETM passenger data not connected.';
frontend/src/pages/HomePage.jsx:45:              <li><StatusBadge tone="warning">Not connected</StatusBadge> Crowd data. ETM passenger data not connected.</li>
frontend/src/pages/AboutPage.jsx:46:        <p>Historical crowd data unavailable. ETM passenger data not connected. Crowd levels need verified electronic ticketing (ETM) records, which have not been o…

### AUDIT 3: coordinates in logs / storage / third-party requests
-- server log lines containing nearby requests (after 800 requests): see /tmp/m4_gate.txt -> coordinate leaks: 0
-- browser: every storage write in frontend source:
frontend/src/features/places/placesStore.js:1:// Saved + recent places, stored ON THIS DEVICE ONLY (localStorage). Stop IDs only: no names, no coordinates, no
frontend/src/features/places/placesStore.js:35:  try { return typeof window !== 'undefined' ? window.localStorage : null; } catch { return null; }
-- every fetch/XHR/beacon call site in frontend source:
frontend/src/api/client.js:69:      response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
-- analytics/tracking identifiers:
frontend/src/hooks/useGeolocation.js:5: * and nowhere else: no storage, no URL, no logging, no analytics (docs/phase4/OPERATIONS.md, privacy).
frontend/src/lib/crowd.js:7: * When crowd data exists, a segment-level payload is expected to look like this (not rendered today):
frontend/src/lib/crowd.js:8: * @typedef {Object} SegmentCrowd
(end analytics grep)
-- external hosts in built html:
http://www.w3.org
https://fonts.googleapis.com
https://fonts.gstatic.com
-- external hosts hardcoded in map code:
(none)
```
```
### AUDIT 4: every new control and its handler (non-test source)
frontend/src/features/map/MapView.jsx:90: <button type="button" className="map__btn" onClick={() => zoom(1)} disabled={phase !== 'ready'} aria-label="Zoom in">+</button>
frontend/src/features/map/MapView.jsx:91: <button type="button" className="map__btn" onClick={() => zoom(-1)} disabled={phase !== 'ready'} aria-label="Zoom out">−</button>
frontend/src/features/map/MapView.jsx:92: <button type="button" className="map__btn map__btn--text" onClick={reset} disabled={phase !== 'ready'}>Reset view</button>
frontend/src/features/map/BottomSheet.jsx:35: <button
frontend/src/features/places/PlacesPanel.jsx:22: {(saved.length > 0 || recentOnly.length > 0) && <Button variant="ghost" size="sm" onClick={places.clearAll}>Clear all saved and recent places</Button>}
frontend/src/features/places/PlacesPanel.jsx:48: <Button size="sm" variant="secondary" onClick={() => places.remove(id)} aria-label={`Remove stop ${id} from your places`}>Remove</Button>
frontend/src/features/places/PlacesPanel.jsx:56: <Button size="sm" variant="secondary" onClick={retry}>Retry</Button>
frontend/src/features/places/PlacesPanel.jsx:57: <Button size="sm" variant="ghost" onClick={() => places.remove(id)} aria-label={`Remove stop ${id} from your places`}>Remove</Button>
frontend/src/features/places/PlacesPanel.jsx:66: <Button size="sm" variant="secondary" onClick={() => onUse?.('from', stop)} aria-label={`Use ${stop.stop_name} as origin`}>From</Button>
frontend/src/features/places/PlacesPanel.jsx:67: <Button size="sm" variant="secondary" onClick={() => onUse?.('to', stop)} aria-label={`Use ${stop.stop_name} as destination`}>To</Button>
frontend/src/features/places/PlacesPanel.jsx:68: {!saved && <Button size="sm" variant="ghost" onClick={() => places.save(id)} aria-label={`Save ${stop.stop_name}`}>Save</Button>}
frontend/src/features/places/PlacesPanel.jsx:69: <Button size="sm" variant="ghost" onClick={() => places.remove(id)} aria-label={`Remove ${stop.stop_name} from your places`}>Remove</Button>
frontend/src/features/places/SaveToggle.jsx:18: <Button variant="secondary" size="sm" aria-pressed={saved} onClick={toggle}>{saved ? 'Saved on this device' : 'Save this place'}</Button>
frontend/src/pages/NearbyPage.jsx:69: <Button onClick={useMine} loading={geo.state === 'requesting'}>Use my location</Button>
frontend/src/pages/NearbyPage.jsx:72: <select value={radius} onChange={(e) => setRadius(Number(e.target.value))} aria-label="Search radius">
frontend/src/pages/NearbyPage.jsx:95: <Button size="sm" variant={fromId === s.stop_id ? 'primary' : 'secondary'} aria-pressed={fromId === s.stop_id} onClick={() => setStop('from', fromId === s.stop_id…
frontend/src/pages/NearbyPage.jsx:96: <Button size="sm" variant={toId === s.stop_id ? 'primary' : 'secondary'} aria-pressed={toId === s.stop_id} onClick={() => setStop('to', toId === s.stop_id ? '' : …
frontend/src/pages/NearbyPage.jsx:107: <Button disabled={!canSearch} onClick={() => navigate(`/journeys?${writeSearch({ fromId, toId })}`)}>Continue to journey search</Button>
frontend/src/features/places/SaveToggle.jsx:18: <Button variant="secondary" size="sm" aria-pressed={saved} onClick={toggle}>{saved ? 'Saved on this device' : 'Save this place'}</Button>
-- controls without an onClick/onChange/onKeyDown/href/to (should be empty):
frontend/src/features/map/BottomSheet.jsx:35:      <button

### AUDIT 5: dependencies
frontend dependencies: {"maplibre-gl":"6.16.0","react":"19.3.1","react-dom":"19.3.1","react-router-dom":"7.18.3"}
overrides: {"@maplibre/geojson-vt":"6.3.0","@maplibre/maplibre-gl-style-spec":"26.4.4"}
frontend dependency diff vs original (direct deps):
1a2
>  "maplibre-gl": "6.16.0",
frontend devDependency diff vs original:
(devDependencies unchanged)
backend requirements.txt diff:
(unchanged: no new runtime Python dependency)
backend requirements-dev.txt diff:
8a9,11
> # Phase 4 property tests (MPL-2.0, test-only, released 2026-10-28; see docs/phase4/DECISIONS.md ADR-03)
> hypothesis==6.170.13
> sortedcontainers==2.4.0
```

## Backend test inventory (`pytest --collect-only -q`)
```
24 tests/test_api.py
28 tests/test_api_v1.py
13 tests/test_calendar.py
17 tests/test_clusters.py
13 tests/test_config.py
7 tests/test_db.py
13 tests/test_gtfs_archive.py
71 tests/test_gtfs_phase1_import.py
28 tests/test_importer.py
22 tests/test_leg_geometry.py
56 tests/test_nearby.py
8 tests/test_planar_properties.py
9 tests/test_real_feed.py
5 tests/test_real_leg_golden.py
125 tests/test_search_relevance.py
51 tests/test_search_unit.py
```
490 collected = 481 passed + 9 skipped (the 9 are `test_real_feed.py`, unchanged). Pre-existing files: 206 collected = 197 passed + 9 skipped. New files: 284.
