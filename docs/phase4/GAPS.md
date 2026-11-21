# Phase 4 — GAPS (documented, not hidden)

Each entry: what, why, impact, what is needed. Ordered by importance to a launch decision.

## G1. No browser was available: all visual and WebGL behaviour is UNVERIFIED
* **What:** `which chromium chrome firefox` found nothing and `npx playwright-core install chromium` failed (`Download failure`; the sandbox's network allow-list excludes browser download hosts). jsdom has no WebGL.
* **Therefore UNVERIFIED** (nothing below was seen on a screen): real MapLibre rendering of the route line, markers, selection ring and accuracy ring; the colours/contrast *on a real basemap* (ratios computed from CSS values only); layout at 320/375/768/1024/1440 px; **no horizontal scroll at 320 px**; the bottom-sheet *drag* with a real pointer (only the keyboard path is tested); touch targets measured on screen (CSS says 44 px); `cooperativeGestures` behaviour on a phone; screenshots at 375 and 1440 px; console errors and failed-request counts in a real page; "map first render < 1.5 s on Fast 3G"; "no long task > 200 ms while panning a 5,000-stop layer".
* **What *is* verified instead:** everything the map is *given* (exact API geometry → GeoJSON, asserted in `MapView.test.jsx` and the page tests), the adapter's layer/source/event/fallback logic against a recording fake of MapLibre (`mapAdapter.test.js`), the production build, the lazy chunk, and the real backend responses.
* **Needed:** run `npm run build && npm run preview` (port 5173) with a style URL in a real browser and walk the checklist in `OPERATIONS.md §7`.

## G2. No real tile provider was configured or exercised
The style-URL path (including the provider's attribution text and a real tile failure) is covered only by tests with a fake engine. **Needed:** choose a provider (ADR-02), restrict its key by domain, confirm rate limits/cost, and check attribution on screen.

## G3. Windows PowerShell commands were not executed
The commands in the final report are the Phase 3 README's Windows commands extended for Phase 4. Everything was *run* on Linux (Python 3.12.3, Node 22.23.4, SQLite 3.45.1). Differences to watch on Windows: the bundled SQLite version/R-tree availability (the build script detects it and falls back to a grid, and records which), path separators, and `inert`/`matchMedia` behaviour in the user's browser.

## G4. Real geolocation was only simulated
Granted / denied / unavailable / timeout / low-accuracy are tested through a stubbed `navigator.geolocation`. Real device accuracy values and permission prompts were not seen.

## G5. Derived data must be rebuilt after every GTFS import
The importer replaces the database file, which drops the derived tables. Not automated (kept out of the importer to leave its all-or-nothing contract untouched). Without a rebuild: search/nearby still work (scan fallback, no clusters), `cluster_id` is absent, `/clusters/{id}` returns 503 `derived_data_missing`. **Needed (optional):** call `build_derived` from `import_gtfs` after promotion.

## G6. Cluster merges to review (listed, not auto-fixed)
4,673 clusters: 2,590 single stops, 2,036 pairs, 38 triples, 9 quads (EVIDENCE M5). **64 multi-stop clusters have a spread over 120 m** (up to 147 m); spot checks of 20 random clusters showed opposite-direction pairs (`…UP` vs `…DOWN`), and 2,065 of 2,083 multi-stop clusters share none of their top-4 routes between first and last member, which is what opposite sides of a road look like. The nine 4-stop clusters (e.g. `KISHAN GANJ DISPENSARY` 147 m, `Metal Forging` 144 m, `Dwarka International School` 144 m, `Hari Nagar Depot` 130 m) are the likeliest to join more than two physical sides and deserve a human look. No suspicious merge was found by the checks that exist; a local reviewer could still find one.

## G7. Headsigns do not exist in this feed
`trip_headsign` empty for 65,322 / 65,322 trips; `stop_headsign` empty; `direction_id` NULL. The UI therefore shows no "towards" text. Route names (`138UP`/`138DOWN`) are the only direction hint and are shown as route names. Passengers cannot be told which way a stop faces beyond bearing/distance from the place centre.

## G8. `shape_dist_traveled` branch never runs on real data
Absent for all stop_times. The branch is unit/synthetic-tested only.

## G9. Some real legs cannot be drawn
5 of 293 randomly sampled real legs (1.7 %) returned `unreliable_projection` (a stop > 60 m from its route's shape; 0.34 % of stop-calls). The UI says "Path could not be matched reliably" and draws no line. Fixing it needs better source data, not a looser threshold.

## G10. Router limits shape the UI
The journey router is still direct-only and takes one origin stop and one destination stop, so the autocomplete never offers "any stop at this place". Pick-on-map yields a *point*; the user must still choose a stop. There is **no keyboard-only way to pick an arbitrary map point** (alternatives: "Use my location", or search by name); the nearby list and map are otherwise keyboard-operable.

## G11. Smart-search coverage
* Ranking deviation from the spec (fuzzy above partial) is intentional (ADR-07).
* Typo tolerance needs tokens ≥ 5 characters, so `nehru plce` (4-letter typo) finds nothing.
* Shipped alias file has zero entries; no Hindi/transliteration (Devanagari input returns an honest empty result with a notice).
* Latency tail: p95 52.7 ms but max 94 ms over 200 queries (budget 150 ms p95).

## G12. Responses are not compressed by the server
`gzip` figures in EVIDENCE are `gzip.compress` of the body (what a compressing proxy would send); the app itself serves identity encoding. The leg endpoint is small either way (9.4 kB raw for the whole 106 km loop), but the legacy full-shape endpoint is 112 kB raw. Adding `GZipMiddleware` was left out to avoid changing every response in this phase.

## G13. Third-party request that pre-dates Phase 4
`index.html` loads Public Sans / Schibsted Grotesk from Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`). That discloses the visitor's IP to Google; it never carries coordinates. Self-hosting the fonts would remove it.

## G14. Hypothesis length property is bounded
"Length within 1 %" is proved for road-like lines (≥ 2 km, ≤ 5 m tolerance) and measured on the real feed (max loss 0.676 % over 2,554 shapes) but is not true for arbitrary noise (ADR-04).

## G15. Not done because the spec says do not
No crowd, ETA, live position or occupancy exists anywhere; the two Phase 3 strings are unchanged.
