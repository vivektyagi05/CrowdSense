# CrowdSense Phase 4 — Final report

Evidence for every number is in `EVIDENCE.md` (commands + real output). **Headline caveat: no browser could be run in this environment, so everything visual is UNVERIFIED (GAPS G1).** Everything else below was executed.

## 1. Audit with real numbers (M1)
Delhi GTFS: 6,812 stops · 2,554 routes · 65,322 trips · 2,385,381 stop_times · 2,554 shapes · 765,633 points. Findings that changed the design:
* `stop_times.shape_dist_traveled` is NULL in **100 %** of rows → stop matching is projection-only on this feed.
* `trip_headsign` / `stop_headsign` empty in **100 %**, `direction_id` NULL → no "towards" labels possible; none invented.
* Exactly **one shape and one stop pattern per route** (a route is one direction); 2,697 trips repeat a stop (loops, longest `2716_04_50`: 183 calls, 1,501 shape points).
* 4,583 stops share a normalised name with another stop (2,124 names); nearest same-name twin: median 27.8 m, p90 120 m. Multi-stop clusters by threshold: 1,702 (50 m) · 2,006 (100) · 2,078 (150) · 2,100 (250) · 2,112 (400).
* 12 stops lie outside 28.0–29.1 N × 76.6–77.8 E; 0 null/zero coordinates; 0 stops without routes; 0 shapes < 2 points; 0 trips without a shape; 0 non-monotone/unordered shapes.
* Existing latency: stop search p95 4.5 ms (substring scan; `kashmire gate`, double spaces, reordered tokens and Devanagari all returned 0); full longest shape 112,797 B raw / 21,678 B gzip. SQLite 3.45.1 has R-tree and FTS5.
* **Privacy bug found:** uvicorn's access log recorded full query strings (would have logged `lat`/`lon`).

## 2. Implementation matrix
| Capability | Before | After | Evidence |
|---|---|---|---|
| Place search | substring only | smart search: typo/reorder/punctuation/case, ranked, grouped | M6: 118 real cases + 7 targeted, p95 52.7 ms |
| Same-name stops | none | 4,673 place clusters (150 m, complete linkage) | M5 stats, hash `5e60fa2b…` |
| Route geometry | whole shape, raw | leg slice, simplified, honest statuses | M3: p95 26 ms, 3.2 kB gz |
| Nearby / spatial | none (full scan) | R-tree (+grid, +scan fallbacks), validated box | M4: 200/200 oracle, p95 3.1 ms |
| Saved places | none | device-local, ids only, capped, validated | places tests (18) |
| Maps in the app | none | journey, route, stop, nearby | tests; **rendering UNVERIFIED** |
| `shape_dist_traveled` | n/a | implemented, dead for Delhi data | synthetic tests only |
| Log privacy | leaked query strings | redacted, mutation-tested | M4 |

## 3. Decisions
15 ADRs in `DECISIONS.md`. Deviations from the spec, all documented: Viterbi matching instead of greedy-in-window (ADR-04); fuzzy ranks above partial (ADR-07); `supercluster` not added (ADR-01); sheet is non-modal (ADR-10); nav unchanged (ADR-11); FTS5 not used (ADR-07).

## 4. Endpoints
Real requests/responses for all of them: `API_CHANGES.md` (12 examples).

## 5. Cluster and search statistics
Clusters: 4,673 = 2,590 single + 2,036 pairs + 38 triples + 9 quads; every stop in exactly one cluster; 64 clusters spread > 120 m flagged for review (G6). Search: the 125-test relevance file (118 generated real-name cases + 7 targeted tests) passes (15 failed on the first run; ranking changed, no case removed); p95 52.7 ms; max 94 ms.

## 6. Frontend architecture
`lib/geo.js` (pure, no line-from-stops function) → `MapView` (declarative, engine once per mount) → `mapAdapter.js` (only MapLibre importer, mockable) ; `LazyMapView` + dynamic import ⇒ engine chunk only on map pages with WebGL. Pages: `JourneyDetailPage` (+`BottomSheet`), `RouteDetailPage` (`RouteMap`), `StopDetailPage` (`StopAround`), `NearbyPage`; `features/places/*`; cluster-aware `StopAutocomplete` (falls back to the flat Phase 3 behaviour when `groups` is absent).

## 7. Per-page real functionality
| Page | What is real |
|---|---|
| Journey details | requests `/trips/{id}/shape?from_stop_id&to_stop_id&board` (never `fallback`), draws the API geometry, board/alight markers, intermediate stops; timeline ⇄ map highlight (hover, focus, click); `no_shape` / `unreliable_projection` / failure → honest message (+Retry) with the full timeline intact |
| Route | shape selector (only when > 1 shape; Delhi has 1 per route), selected trip's ordered stops, callout linking to the stop page; map loads *after* the text list |
| Stop | this stop, same-place siblings with distance/bearing from the centre and routes, nearby stops within 400 m (from the **stop's** coordinates), save toggle |
| Nearby `/nearby` | "Use my location" (click only), tap-to-search, radius select (changes the request), accuracy ring + > 200 m warning, "Use as origin / destination" (stop ids only), continue to journey search; reachable from the home page |
| Home / journeys | cluster-aware autocomplete (place heading + one selectable row per real stop with routes and offset from centre; no "any stop"), "Your places" panel (stale ids reported, removable, clear-all) |

## 8. Tests: new vs existing
| Suite | Phase 3 | Phase 4 | New |
|---|---|---|---|
| Backend pytest | 197 passed, 9 skipped | **481 passed, 9 skipped** | +284 (pytest `--collect-only`: leg geometry 22, RDP properties 8, real golden 5, nearby 56, clusters 17, search relevance 125, search unit 51; 490 collected = 481 passed + 9 skipped) |
| Frontend vitest | 106 passed, 1 skipped | **222 passed, 4 skipped** | +116 (geo 18, MapView 16, adapter 14, journey map 7, route/stop maps 11, nearby 17, clusters AC 8, places 18, a11y 7) |
| Live (real backend + data) | 1 | **4 passed** | +3 |
Existing tests: **0 deleted, 0 skipped-newly, 0 weakened**; all pre-existing test files/fixtures byte-identical to the Phase 3 ZIP except `src/test/setup.js` (storage isolation, ADR-14). Two of my own changes initially broke existing tests (`RouteShapeRef` nulls; `cluster_id: null`; nav list; first `/stop-times` call order); each was fixed in the code, not the test.

## 9. Browser QA
**Not possible here.** No browser binary; Playwright's browser download failed (`Download failure`). Every visual item is UNVERIFIED: see GAPS G1 and the checklist in `OPERATIONS.md §7`. No screenshots exist at 375 or 1440 px, and console-error / failed-request counts for a real page are unknown.

## 10. Performance vs budget
| Budget | Measured | Status |
|---|---|---|
| Leg shape p95 < 120 ms (longest route) | 26.0 ms | met |
| Leg payload ≤ 40 kB gzip | 3.2 kB | met |
| Nearby p95 < 40 ms | 3.1 ms (3000 m / 50 results: 5.2 ms) | met |
| Search p95 < 150 ms | 52.7 ms | met |
| Entry bundle ≤ +2 kB gzip | **−2.31 kB** (101.82 vs 104.13) | met |
| Map chunk only when a map is shown | verified in the build output; 1,060 kB / 288 kB gzip (+10.3 kB CSS) | met (large, inherent to MapLibre) |
| Map first render < 1.5 s on Fast 3G | not measured | **UNVERIFIED** |
| No long task > 200 ms panning 5,000 stops | not measured (the adapter feeds one GeoJSON source) | **UNVERIFIED** |
Clean-clone backend startup and `npm run build` both succeed (EVIDENCE M13).

## 11. Files
Created (34 paths, plus `docs/phase4/*`): `backend/app/derived`, `backend/app/geo`, `backend/app/services/cluster_service.py`, `backend/app/services/leg_service.py`, `backend/app/services/nearby_service.py`, `backend/app/services/search_service.py`, `backend/data/aliases`, `backend/scripts/audit_m1_db.py`, `backend/scripts/audit_m1_latency.py`, `backend/scripts/audit_m3_gate.py`, `backend/scripts/audit_m3_projection.py`, `backend/scripts/audit_m4_gate.py`, `backend/scripts/audit_m5_clusters.py`, `backend/scripts/audit_m6_gate.py`, `backend/scripts/build_derived.py`, `backend/tests/geo_world.py`, `backend/tests/test_clusters.py`, `backend/tests/test_leg_geometry.py`, `backend/tests/test_nearby.py`, `backend/tests/test_planar_properties.py`, `backend/tests/test_real_leg_golden.py`, `backend/tests/test_search_relevance.py`, `backend/tests/test_search_unit.py`, `frontend/src/a11y.phase4.test.jsx`, `frontend/src/features/map`, `frontend/src/features/places`, `frontend/src/features/search/StopAutocompleteClusters.test.jsx`, `frontend/src/hooks/useGeolocation.js`, `frontend/src/lib/geo.test.js`, `frontend/src/live.phase4.test.jsx`, `frontend/src/pages/JourneyDetailMap.test.jsx`, `frontend/src/pages/NearbyPage.jsx`, `frontend/src/pages/NearbyPage.test.jsx`, `frontend/src/pages/RouteStopMaps.test.jsx`.
Modified (28): `CHANGELOG.md`, `README.md`, `backend/app/__main__.py`, `backend/app/api/network.py`, `backend/app/api/stops.py`, `backend/app/logging_config.py`, `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/services/stops_service.py`, `backend/requirements-dev.txt`, `docs/API.md`, `frontend/.env`, `frontend/package-lock.json`, `frontend/package.json`, `frontend/src/App.jsx`, `frontend/src/api/endpoints.js`, `frontend/src/config.js`, `frontend/src/features/journeys/JourneyTimeline.jsx`, `frontend/src/features/search/JourneySearchForm.jsx`, `frontend/src/features/search/StopAutocomplete.jsx`, `frontend/src/lib/geo.js`, `frontend/src/pages/HomePage.jsx`, `frontend/src/pages/JourneyDetailPage.jsx`, `frontend/src/pages/RouteDetailPage.jsx`, `frontend/src/pages/StopDetailPage.jsx`, `frontend/src/styles/components.css`, `frontend/src/styles/pages.css`, `frontend/src/test/setup.js`.
Removed: none.

## 12. Gaps and risks
`GAPS.md` (15 entries). Top five: **(1) nothing visual verified in a browser**; (2) no tile provider chosen/tested; (3) Windows PowerShell not executed here; (4) derived data must be rebuilt after each import; (5) 64 clusters > 120 m spread deserve human review.

## 13. Exact Windows PowerShell commands
```powershell
# one-time backend setup
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env                       # optional
# GTFS import (put delhi_buses_static_gtfs_v1.zip in backend\data first), then DERIVED DATA (new, required after every import)
python -m scripts.import_gtfs
python -m scripts.build_derived                   # add --force-grid to test the non-R-tree fallback
# backend tests
python -m pytest -q
# start the backend (terminal 1)  http://127.0.0.1:8000  docs at /docs
python -m app
# frontend (terminal 2)
cd ..\frontend
npm ci
Copy-Item .env .env.local                         # optional; then uncomment/set VITE_MAP_STYLE_URL for a street basemap
npm test                                          # 222 passed, 4 skipped
npm run build                                     # production build
npm run preview                                   # http://localhost:5173 (port is fixed: backend CORS)
# or development: npm run dev
# live integration tests against the running backend (real data)
$env:CROWDSENSE_LIVE_API = "http://127.0.0.1:8000/api/v1"; npx vitest run src/live.test.jsx src/live.phase4.test.jsx; Remove-Item Env:CROWDSENSE_LIVE_API
# everything at once (unchanged Phase 3 script)
cd ..; powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
```
These were **not run on Windows** (G3); the equivalent Linux commands were.

## 14. Status per feature
| Feature | Implemented | Automated-tested | Browser-verified | Unverified |
|---|---|---|---|---|
| Leg geometry endpoint (+loops, +statuses) | yes | yes (22 synthetic + 5 real golden + 8 property + live) | n/a (API) | — |
| Route shapes `?geometry=true` | yes | yes | n/a | — |
| Nearby endpoint + R-tree/grid/scan | yes | yes (oracle 200/200 ×3 paths; real 200/200) | n/a | Windows SQLite R-tree availability |
| Log privacy (coordinates) | yes | yes (+mutation check, 800 real requests) | n/a | reverse-proxy logs (out of scope) |
| Derived build (idempotent, hash) | yes | yes (+clean clone) | n/a | — |
| Place clusters + `/clusters/{id}` | yes | yes | n/a | human review of 64 wide clusters |
| Smart search (+typo, +abuse) | yes | yes (118 real cases + 7 targeted) | n/a | — |
| Alias loader (0 shipped entries) | yes | yes | n/a | no aliases exist |
| Map engine adapter + MapView | yes | yes (mock engine, 30 tests) | **no** | real rendering, WebGL, GPU |
| Journey details map + highlight sync | yes | yes (7 + live) | **no** | on-screen behaviour |
| Route page map + shape selector | yes | yes (6) | **no** | on-screen behaviour |
| Stop page map (cluster, nearby) | yes | yes (5) | **no** | on-screen behaviour |
| `/nearby` + geolocation states | yes | yes (17, stubbed geolocation) | **no** | real device accuracy/prompts |
| Pick on map | yes | yes (adapter + page) | **no** | real taps; no keyboard equivalent (G10) |
| Cluster-aware autocomplete | yes | yes (8 + all 10 Phase 3 tests + live) | **no** | — |
| Saved / recent places | yes | yes (18) | **no** | real private-mode browsers |
| Fallbacks: no style / tile error / no WebGL / slow / no shape / geolocation denied | yes | yes (each has a test) | **no** | real tile failures |
| Lazy chunk, entry budget | yes | build output checked | n/a | Fast-3G first render |
| Contrast (new text/markers) | yes | computed from CSS values | **no** | on a real basemap |
| Responsive 320–1440, 44 px targets, sheet drag | yes (CSS) | keyboard path only | **no** | all layout/visual checks |
| Street basemap + attribution | yes (configurable) | engine fake | **no** | no provider chosen |

## 15. Self-audit (spec §18)
1. **Straight line between stops as a route?** NO. The only line builder is `lineFeature(coordinates)` in `lib/geo.js`, fed solely by API geometry with `status: ok`; no frontend code requests `fallback=stops`; tests assert the request has no `fallback` and that a non-ok status with smuggled coordinates draws nothing (EVIDENCE audit 1).
2. **Crowd/live/ETA value anywhere?** NO. No match in any Phase 4 file; the two Phase 3 strings are unchanged.
3. **User coordinates in logs / storage / third-party requests?** NO. Server: 0 leaks over 800 real logged requests, mutation-checked test; browser: the only storage write is the places store (ids only); the only `fetch` call site goes to our own API; MapLibre fetches tiles for the *viewed area* from whatever style you configure (disclosed, ADR-02/08). Pre-existing: Google Fonts (G13).
4. **Control without a working handler?** NO (all listed in EVIDENCE audit 4; every one has a handler and a test).
5. **Dependency without ADR / exact pin / licence check?** NO. One new runtime dep (`maplibre-gl 6.16.0`), two pinned overrides, two dev-only Python pins; 25-package closure audited (youngest 20 days, permissive licences).
6. **Existing test deleted/skipped/weakened?** NO (byte-identical except `setup.js` storage isolation).
7. **Works when tiles fail, WebGL missing, geolocation denied, trip has no shape?** YES, by automated test: `MapView.test.jsx` (degradation matrix), `mapAdapter.test.js` (tile failure → blank style), `NearbyPage.test.jsx` (denied/unavailable/timeout), `JourneyDetailMap.test.jsx` + `leg_geometry` (no shape). **Not seen in a real browser.**
8. **Every report number traceable to EVIDENCE.md?** YES; the per-milestone tables quote the pasted outputs.
