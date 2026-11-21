# CrowdSense Phase 3: Product transformation and frontend engineering

## 1. Repository audit (what was actually found)

Audited from `CrowdSense_Phase1_GTFS_Data_Platform.zip`. The shipped archive contained **no built database**; the real Delhi
GTFS zip was imported with `python -m scripts.import_gtfs` (6,812 stops, 2,554 routes, 65,322 trips, 2,385,381 stop-times,
2,554 shapes) and every backend claim below was checked against the running API.

Baseline before changes: backend 197 passed / 9 skipped; frontend 33 passed.

| Capability | Backend (verified) | Frontend before | Action taken |
|---|---|---|---|
| Stop search | `/stops?q=` works, paginated | plain input, no selection model | rebuilt as accessible combobox (`StopAutocomplete`) |
| Journey search | `/journeys` is **direct, single-bus only** (`mode: direct_only`). No transfers, no sort or filter parameters, no journey id | one page, ad-hoc | UI built on what exists; see section 2 |
| Journey details | no endpoint; `/trips/{id}` + `/trips/{id}/stop-times` exist | none | details page assembles a leg from those real records |
| Stops / routes / trips / shapes | all present, paginated | none | Explore, Stop, Route pages |
| Calendar / summary / validation | present | partial | Insights and About pages |
| Crowd | `crowd.status = NOT_AVAILABLE` on every journey | n/a | rendered honestly, never estimated |
| Router / multi-page | n/a | single `App.jsx` | `react-router-dom` 7.18.3 (the only new dependency, pinned) |

Findings worth knowing:
* Phase 2 transfer routing is **not implemented** in this codebase. Nothing in the UI pretends otherwise.
* Within one stop pair, direct trips almost always have identical durations (timetable-generated), so "Fastest" often ties.
  The sort control still works; it is exercised in tests with a modified response.
* Many stops share a name (for example two "Alpana Cinema" stops), so stop ids and coordinates are shown to tell them apart.
* The old `datetime.js` defaulted to the browser timezone; replaced by a Delhi-timezone strategy (`lib/time.js`).

## 2. Honest deviations from the brief

| Brief | What was done and why |
|---|---|
| Transfer-limit control | Not exposed. The engine cannot transfer, so a control would be inert. The form says "Direct buses only". |
| Sorts: fastest / fewest transfers / balanced | Implemented in `lib/journeys.js` (balanced = duration + 12 min per transfer). The UI offers only orderings that can reorder the current result set: earliest departure, fastest, earliest arrival; fewest-transfers and balanced appear automatically when a result set contains different transfer counts. |
| Journey id | Stable URL: `/journeys/:tripId?from&to&date&board=HH:MM:SS` (board time disambiguates loop routes). |
| Filters | Client-side over the returned candidate set (the 30 earliest departures), stated on the page: route, longest journey, departure window. Held in the URL. |
| Charts | One real chart: trips running vs not running on a chosen date (`/services/active`). Other tables are stat tiles, because bars of 6,812 stops against 2.4 million stop-times would mislead. |
| Browser QA / screenshots | **Not done**: no browser could be installed in this environment (Playwright's browser download is blocked). See section 7. |

## 3. Information architecture

`/` plan journey, `/journeys` results, `/journeys/:tripId` details, `/explore` (tabs Stops / Routes), `/stops/:stopId`,
`/routes/:routeId`, `/insights`, `/about`, `*` not found. Persistent header with logo (home) and primary nav (menu button
below 900px), skip link, footer stating that times are scheduled. Pages are lazy-loaded chunks.

## 4. Architecture

```
src/
  api/        client.js (timeout, cancellation, error parsing, opt-in retry of transient failures only)
              endpoints.js (every backend call), cache.js (reference data + in-flight dedupe)
  lib/        time.js (Delhi tz), journeys.js (view-model, sort, filter), searchParams.js (URL state),
              journeyDetail.js, crowd.js (contract), geo.js (map-readiness boundary), title.js
  hooks/      useAsync (cancel + stale protection + retry), useStop, useDebouncedValue, useBackendStatus
  ui/         design-system components (Button, Field/Input/Select/DateTimeField, Tabs, Badges, States,
              Pagination, Modal (native dialog), Toast, Stat, Icon)
  features/   search/ (StopAutocomplete, JourneySearchForm), journeys/ (Card, Filters, Timeline, Compare, CrowdStatus)
  pages/      one file per route
  styles/     tokens.css (colour, type, space, radius, shadow, layout), base.css, components.css, pages.css
```
Data ownership: server data via `useAsync` (+ small cache for reference data), search/filters in the URL, temporary UI
state (menu, compare selection) in components. No Redux/Zustand: nothing needed it.

## 5. Design system

Premium urban-mobility look: forest-green primary (`--forest-800`), emerald action accents, warm neutral surfaces,
Schibsted Grotesk (display) + Public Sans (body), tabular numerals for times, restrained borders/shadows. Signature element:
the journey timeline drawn as a transit line. All colours and sizes come from tokens; every page uses the shared components.

## 6. Functionality status

Implemented and covered by automated tests (jsdom): routing, 404, nested-URL restore, history back/forward, mobile menu,
backend-down banner; autocomplete (debounce, min length, cancellation, stale response, keyboard, escape, clear, retry,
invalid selection); swap, validation, URL restore; results (real fixtures), route/duration/time filters, sorting, compare,
three no-result variants, error and retry, invalid and unknown-stop links; details (full leg, direct URL, incomplete,
missing, mismatched); explore, stop, route; insights; about; accessibility basics on every page.

Fixtures in `src/test/fixtures` are responses **recorded from the real backend**. One sorting test uses a deliberately
modified copy (labelled in the test). Multi-leg *rendering* is covered at the view-model level (`journeyFromLegs`) and by
`JourneyTimeline` accepting multiple legs, but no real multi-leg journey exists to display.

## 7. Verification, separated

| Level | Result |
|---|---|
| Automated, jsdom, recorded real responses | 106 tests pass |
| Automated, jsdom, **live real backend** (`CROWDSENSE_LIVE_API`) | passes: stop search to journeys to details to route |
| Backend suite | 197 passed, 9 skipped (unchanged, no backend edits) |
| Production build | succeeds; SPA fallback and CORS from the preview origin verified with curl |
| **Real browser, console errors, screenshots, mobile viewport** | **NOT verified** (no browser available) |
| Contrast / responsive layout | designed to the rules (tokens, 900px and 640px breakpoints, 44px targets) but not visually verified |

## 8. Bundle (gzip)

Entry chunk 104 kB (React, router, shell); CSS 5.5 kB; each page 1-4 kB gzip, loaded on demand. Total build 468 kB on disk.

## 9. Not done / blockers

Browser QA and screenshots; transfer routing (a backend phase); map rendering (Phase 4; `lib/geo.js` is the boundary);
crowd data (needs ETM data); ESLint is not configured in this repo.

## 10. Run on Windows PowerShell

```powershell
# one-time backend setup
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env   # only if .env is missing
New-Item -ItemType Directory -Force data | Out-Null
# put delhi_buses_static_gtfs_v1.zip in backend\data, then:
python -m scripts.import_gtfs
python -m app                 # http://127.0.0.1:8000

# frontend (second terminal)
cd frontend
npm ci
npm run dev                   # http://localhost:5173
npm test
$env:CROWDSENSE_LIVE_API = "http://127.0.0.1:8000/api/v1"; npx vitest run src/live.test.jsx   # live test, backend running
npm run build; npm run preview
```
