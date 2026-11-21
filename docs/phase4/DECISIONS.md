# Phase 4 — DECISIONS (ADR log)

Format per decision: **Options → Choice → Reason → Consequences → How to reverse.** Numbers cite `EVIDENCE.md`.

---
## ADR-01 Map engine: MapLibre GL JS 6.16.0
* **Options:** Leaflet (raster, DOM markers), deck.gl (GPU layers, needs a base map library anyway), MapLibre GL JS (vector, WebGL).
* **Choice:** `maplibre-gl@6.16.0` (BSD-3-Clause). Newest release that is ≥ 14 days old on 2026-11-14 (published 2026-10-25, 20 days at audit time; 6.17.0 was 6 days old).
* **Reason:** vector style control (the basemap can be swapped or removed by changing one URL, which the degradation matrix needs); native GeoJSON sources so a route line and thousands of stops are GPU layers, not DOM nodes; BSD licence with no key or account requirement for the engine itself. Leaflet would need DOM markers for stops and a raster provider, deck.gl adds a second library for little gain at 10²–10⁴ points.
* **Consequences:** the engine is large (1,060 kB / 288 kB gzip) — mitigated by lazy loading (ADR-09). MapLibre 6 has **named exports only**; this was caught by `vite build` and not by unit tests (EVIDENCE M7) so the adapter test mock now mirrors the real module shape. Clustering of stops is *not* used (pages draw ≤ ~200 stops); `supercluster` was therefore **not added** (spec: "only if justified").
* **Reverse:** everything map-specific is behind `src/features/map/mapAdapter.js` (one file, ~14 methods); replacing the engine means rewriting that file and nothing else.

## ADR-02 Tiles / basemap provider, service area, attribution, failure behaviour
* **Facts verified:** the OpenStreetMap Foundation tile usage policy (operations.osmfoundation.org/policies/tiles) says the public tile servers are not for heavy or production use, may be blocked without notice, and that the data must be attributed; the vector tile policy is similarly restrictive.
* **Options:** (a) hard-code `tile.openstreetmap.org` — rejected; (b) a hard-coded managed provider — rejected (key in repo); (c) **no default; operator supplies `VITE_MAP_STYLE_URL`** (managed provider or self-hosted vector tiles).
* **Choice:** (c). With no style URL the map draws the real route and stops on a plain background (`BLANK_STYLE`, zero third-party requests) and says "No street basemap is configured".
* **Provider requirements** (documented in `OPERATIONS.md`): style JSON over https (http only for localhost); a browser-side key is **visible to every visitor** → restrict it by HTTP referrer/domain at the provider; know the provider's rate limits and cost before launch; the provider's attribution is rendered by MapLibre's attribution control from the style, and we always add "Route and stop data: Delhi GTFS (static timetable)".
* **Failure behaviour:** style or tile errors switch the map to `BLANK_STYLE` (layers and data re-applied on `style.load`) and show "Street tiles could not be loaded"; WebGL missing → the engine is never downloaded and a "Map unavailable" card lists the stops; engine chunk 404 → same card; slow load → notice after 6 s. Each has a test (EVIDENCE M12).
* **Service area box:** 28.00–29.50 N, 76.40–77.80 E. The stop extent is lat 28.208–29.341, lon 76.601–77.431 and 12 stops lie outside the tighter 28.0–29.1 × 76.6–77.8 box, so the box was widened until it contained all 6,812 stops (verified in EVIDENCE M4).
* **Privacy caveat (honest):** the provider never receives the user's coordinates from us, but any basemap provider sees which tiles (the general area) are loaded. The Nearby page says so.
* **Reverse:** unset the variable.

## ADR-03 Dependencies (exact pins, licence, age)
| Package | Where | Pin | Licence | Why |
|---|---|---|---|---|
| `maplibre-gl` | frontend runtime | 6.16.0 | BSD-3-Clause | ADR-01 |
| `@maplibre/geojson-vt` | transitive, **overridden** | 6.3.0 | ISC | the declared range `^6.3.0` resolved to 6.3.1, published **3 days** before the audit — violating the two-week rule |
| `@maplibre/maplibre-gl-style-spec` | transitive, **overridden** | 26.4.4 | ISC | range `^26.4.4` resolved to 26.7.0, published **0 days** before the audit |
| `hypothesis` | backend dev/test only | 6.170.13 | MPL-2.0 (test-only, not shipped) | property tests for RDP (spec §6 requires Hypothesis, "pin and justify"); 6.170.13 released 2026-10-28 (17 days) |
| `sortedcontainers` | backend dev/test only, via hypothesis | 2.4.0 | Apache-2.0 | hypothesis dependency |

No new **runtime** Python dependency (`requirements.txt` is byte-identical to Phase 3). Transitive audit of the whole `maplibre-gl` closure (lockfile + registry, 2026-11-15):

```
package@version | licence | published | age (days)
maplibre-gl@6.16.0 | BSD-3-Clause | 2026-10-25 | 20
@mapbox/point-geometry@1.1.0 | ISC | 2024-07-16 | 852
@mapbox/tiny-sdf@2.3.0 | BSD-2-Clause | 2026-10-08 | 37
@mapbox/unitbezier@1.0.0 | BSD-2-Clause | 2026-05-26 | 172
@mapbox/vector-tile@3.0.0 | BSD-3-Clause | 2026-05-27 | 172
@types/geojson@7946.0.16 | MIT | 2025-01-23 | 660
pbf@5.1.2 | BSD-3-Clause | 2026-07-09 | 128
resolve-protobuf-schema@2.1.0 | MIT | 2018-07-20 | 3039
protocol-buffers-schema@3.6.1 | MIT | 2026-04-06 | 222
@maplibre/geojson-vt@6.3.0 | ISC | 2026-10-16 | 29
kdbush@4.1.0 | ISC | 2026-05-19 | 179
@maplibre/maplibre-gl-style-spec@26.4.4 | ISC | 2026-09-15 | 60
@mapbox/jsonlint-lines-primitives@2.0.3 | MIT | 2026-06-25 | 142
json-stringify-pretty-compact@4.0.0 | MIT | 2022-05-14 | 1645
minimist@1.2.8 | MIT | 2023-02-09 | 1374
quickselect@3.0.0 | ISC | 2024-07-03 | 865
tinyqueue@3.0.0 | ISC | 2024-07-06 | 862
@maplibre/mlt@1.3.0 | (MIT OR Apache-2.0) | 2026-09-12 | 63
@maplibre/vt-pbf@4.3.3 | MIT | 2026-10-25 | 21
bidi-js@1.1.0 | MIT | 2026-09-06 | 69
require-from-string@2.0.2 | MIT | 2018-04-09 | 3142
earcut@3.2.4 | ISC | 2026-09-28 | 48
gl-matrix@3.4.4 | MIT | 2025-08-08 | 463
murmurhash-js@1.0.0 | MIT | 2014-04-29 | 4583
potpack@2.1.0 | ISC | 2025-07-14 | 489

closure size: 25 packages; youngest: 20 days; licences: BSD-3-Clause, ISC, BSD-2-Clause, MIT, (MIT OR Apache-2.0)
```
Transitive versions are fixed by `package-lock.json` (`npm ci`) and the two `overrides` in `package.json`.
* **Reverse:** remove `maplibre-gl` and the overrides; remove the three lines from `requirements-dev.txt`.

## ADR-04 Leg geometry algorithm (documented deviations from spec §6)
* **Implemented as specified:** load trip calls + shape; resolve boarding call (departure == `board`, else first call at that stop) and alighting (first *later* call at `to_stop_id`, loop-safe); map stops to positions; slice with interpolated end points; RDP in a local metric plane (never degrees), default 5 m, clamped 1–50 m, first/last preserved; structured `no_shape` / `unreliable_projection`; response fields as specified plus `length_original_m`, `match_method`, `match_threshold_m`.
* **Deviation 1 — Viterbi instead of greedy "nearest within a monotone window".** A greedy nearest point picks the wrong pass on out-and-back or loop geometry. Candidates are the per-segment projections within the threshold; a dynamic program minimises the summed stop-to-line distance subject to non-decreasing position along the line, so the *whole* trip decides ambiguous passes. Tests: rectangle loop, out-and-back on the same road, loop whole-trip (`test_leg_geometry.py`), and the real longest loop trip `2716_04_50` (106.5 km).
* **Deviation 2 — `shape_dist_traveled` branch is dead for Delhi.** It is NULL in 2,385,381 / 2,385,381 stop_times (M1). The branch is implemented (used only when stop and shape distances are all present, non-decreasing and consistent with the geometry within the threshold) and tested synthetically, including the rejection cases; the importer already rejects a decreasing `shape_dist_traveled`.
* **Threshold 60 m:** measured over all 86,326 stop-calls of one trip per route: median 2.3 m, p95 12.2 m, p99 29.3 m, **99.66 % within 60 m**, 99.92 % within 100 m, max 189.1 m. 60 m keeps false rejections at 0.34 % while stopping a stop on a parallel road from being "snapped" to the wrong line.
* **Performance:** a uniform-grid segment index (200 m cells, built per request) keeps the full 183-call loop at p95 26 ms (budget 120).
* **Length property:** the spec's "length within 1 %" is proved by Hypothesis for road-like lines ≥ 2 km at ≤ 5 m, and measured on all 2,554 real shapes (max loss **0.676 %**). It is *not* a theorem for adversarial noisy lines (a tolerance larger than the noise amplitude can shorten them arbitrarily); the test docstring says so.
* **Reverse:** `get_leg_shape` is one function; the matcher is `geo/planar.py::monotone_match`.

## ADR-05 Place clusters
* **Rule:** same normalised name (NFKC, case-fold, punctuation/symbols/whitespace → single space; combining marks kept so Devanagari survives) **and** true agglomerative *complete linkage* ≤ **150 m**, ties broken by sorted member ids (order-independent; tested with 20 shuffles).
* **Why 150 m (M1 histograms):** multi-stop clusters at 50/100/150/250/400 m = 1,702 / 2,006 / 2,078 / 2,100 / 2,112. 150 m captures 98.4 % of what 400 m would, and growth afterwards is tiny; 88 % of same-name stops have a twin within 100 m (median nearest twin 27.8 m). Complete linkage (not single) stops A–B–C chains from merging stops 200 m apart.
* **Suffix variants are NOT merged.** Evidence: only 5 of 20 `X` / `X Metro Station` pairs and 5 of 26 `terminal` pairs lie within 150 m (e.g. `nangloi` ↔ `nangloi metro station` = 252 m); railway-suffix pairs: 0. A wrong merge puts a passenger on the wrong stop, so we do not guess.
* **Ids:** `c_` + first 12 hex of SHA-1 of the sorted member ids → stable across rebuilds.
* **Distinguishing info:** coordinates, serving routes (the feed's route names carry `UP`/`DOWN`), bearing and distance from the centroid, scheduled call count. **No "towards X" labels**: `trip_headsign` and `stop_headsign` are empty for 100 % of the feed (M1), so `headsigns` is `[]` and `headsigns_available` is false; they appear automatically if a future feed publishes headsigns.
* **Reverse:** `CLUSTER_THRESHOLD_M` in `app/derived/build.py`; rebuild.

## ADR-06 Derived data: one idempotent script, same SQLite file, graceful fallbacks
* `python -m scripts.build_derived` builds `stop_routes`, the spatial index, `clusters`, `cluster_members`, `derived_meta` **in one transaction** (a failed rebuild leaves the previous derived data intact — tested). The content hash covers the derived rows and is identical across repeated runs and across a clean clone (`5e60fa2b…`); `built_at` and a source fingerprint are metadata.
* **Spatial index:** SQLite R-tree when compiled in (checked via `PRAGMA compile_options`; it is here, 3.45.1), else an indexed 0.005° grid (selectable with `--force-grid`; both are oracle-tested), else a bounding-box scan if derived data was never built. `index` in the response says which answered.
* **Cost:** the importer replaces the database file, so derived data must be rebuilt after each import (documented; the API still works without it, with `cluster_id` omitted and `/clusters` returning 503 `derived_data_missing`).
* **Reverse:** delete the derived tables; nothing else depends on them.

## ADR-07 Smart search
* **Design:** in-memory index built once per database file (and at startup), ~4.4k distinct names; per query: normalise → exact/alias/prefix/token matching → bounded Levenshtein ≤ 2 for query tokens ≥ 5 chars (vocabulary bucketed by length, expansions memoised, memo capped at 5,000) → rank → group by cluster. **FTS5 was not used**: the scan is 5–10 ms, adds no platform dependency on SQLite build flags (a user's Windows Python ships its own SQLite), and FTS5 prefix/trigram would not give edit-distance tolerance anyway.
* **Ranking:** exact 1000 > alias 900 > prefix 800 > all_tokens 600 > **fuzzy 500** > partial_tokens ≤ 400; ties: more routes, shorter name, stable id. `match_type` and `score` are returned.
* **Deviation (documented):** the spec orders fuzzy last. The relevance suite showed that this ranks `Azadpur Metro Station` (a *partial* match that ignores the misspelled word) above `Rithala Metro Station` for `Rihala Metro Station`, where *every* token is accounted for. A fuzzy match covering all query tokens now ranks above partial matches (it is still labelled `fuzzy`).
* **Prefix tests assert completeness, not rank:** `punjabi bag` has 21 legitimate prefix matches; the right property is that the target is in the prefix set and prefix matches outrank weaker kinds.
* **Aliases:** loader, validation and tests are shipped; the shipped CSV has **zero entries**. Naming variants present in the GTFS are already handled by normalisation/typo tolerance; a Hindi/transliteration dictionary would be invented data (rule 4). An invalid alias file disables aliases (logged at ERROR) instead of breaking search.
* **Abuse protection:** `q` 2–80 characters after normalisation, `limit` ≤ 50, `mode=smart` accepts only `q` and `limit`, query never reaches SQL (matched in memory; all other SQL is parameterised), hostile inputs tested (SQL, control characters, emoji, 80-char and repeated-token inputs).

## ADR-08 Privacy of user coordinates
* uvicorn's default access log printed full query strings (`GET /stops/nearby?lat=…&lon=…`) — a real leak found in M1. Fix: `RedactCoordinatesFilter` on `uvicorn.access`/`uvicorn.error`/`app` loggers and their handlers (values of `lat`, `lon`, `latitude`, `longitude`, `lng` become `[redacted]`). Proven by (a) a unit test, (b) a test that starts the real `python -m app`, sends valid, out-of-area and malformed coordinates and greps all output, and (c) a **mutation check**: with the filter disabled, (b) fails. Over 800 real requests the log contained 0 coordinate leaks (EVIDENCE M4).
* Error handlers log only the path (verified). Responses never echo the coordinates back except the normal result data.
* Browser: geolocation only after clicking "Use my location", `maximumAge: 0`, 10 s timeout, position kept in React state only (never URL, storage or logs; tested); coordinates go only to our own `/stops/nearby`; `getNearbyStops` is not cached. Saved places hold stop ids only.

## ADR-09 Frontend architecture
`lib/geo.js` (pure data prep; **no function can build a line from stops**) → `features/map/MapView.jsx` (declarative: data in, callbacks out; engine created once per mount) → `features/map/mapAdapter.js` (the only importer of MapLibre; mockable boundary). `LazyMapView` + a dynamic `import()` inside `MapView` give a separate engine chunk loaded only when a map renders **and WebGL exists**. Result: entry chunk 319.10 kB / **101.82 kB gzip vs baseline 326.35 / 104.13 (−2.31 kB)**.

## ADR-10 Bottom sheet is not a Modal
The spec asks for a draggable bottom sheet *and* that sheets use the existing Modal pattern *and* that focus is never trapped. A modal traps focus and blocks the map, so the sheet is a non-modal `fixed` panel on phones only (< 768 px), a normal block beside the map elsewhere. Its handle is a real button (Enter/Space cycles collapsed/half/full, `aria-expanded`, `aria-controls`) that also responds to a vertical drag; collapsed content is `inert` on phones so hidden controls cannot take focus. The sheet is used where the details are the page (journey details, nearby). Route and stop pages stack the map above their details instead: a permanent fixed sheet would cover their long pages.

## ADR-11 Primary navigation left unchanged
An existing Phase 3 test pins the exact primary-nav link list. Rather than edit that assertion, `/nearby` is reachable from the home page ("Find stops near you…") and linked back from journeys; the nav is unchanged.

## ADR-12 Colour contrast for new UI
All new text pairs pass WCAG AA (≥ 7 for most). The Phase 3 token `--border-strong` is only **1.51:1** on white, below the 3:1 WCAG 1.4.11 needs to identify a control boundary; it is pre-existing and left alone. New Phase 4 controls use `--ink-500` (4.97:1) through `--control-edge`. Full table: EVIDENCE M11.

## ADR-13 Caching
Only immutable reference data is cached: place clusters (by id). Nearby results, leg shapes and search results are not cached; `useAsync` aborts on unmount and supersession and de-dupes under React StrictMode (tested).

## ADR-14 One test-infrastructure change
`frontend/src/test/setup.js` now clears `localStorage` and the places-store cache after each test (the device-local places store would otherwise leak between tests). No assertion changed; every other pre-existing test, fixture and helper is byte-identical to the Phase 3 ZIP (EVIDENCE M12).

## ADR-15 `cluster_id` is omitted, not null
Adding `cluster_id: null` to stop responses failed six pre-existing exact-match tests. A wrap serializer drops the key when there is no cluster, so a database without derived data returns exactly the Phase 3 bytes; with derived data the field is present.
