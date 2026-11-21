# Phase 4 — OPERATIONS

## 1. Everything from a clean clone (Linux/macOS shell; Windows PowerShell version in the final report)
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt            # requirements.txt for runtime only
python -m scripts.import_gtfs                  # ~25 s; replaces data/crowdsense.sqlite3 (all-or-nothing)
python -m scripts.build_derived                # ~5 s; REQUIRED after every import (see §2)
python -m pytest -q                            # 481 passed, 9 skipped on the reference run
python -m app                                  # http://127.0.0.1:8000 , docs at /docs
cd ../frontend
npm ci && npm test && npm run build            # 222 passed, 4 skipped (live tests); build green
npm run dev                                    # or: npm run preview   (port 5173 is fixed: backend CORS allows only it)
```

## 2. Derived data (`python -m scripts.build_derived [--db FILE] [--force-grid]`)
Builds, in one transaction: `stop_routes`, the spatial index (`stops_rtree`, or `stops_grid` when R-tree is not compiled in or `--force-grid`), `clusters`, `cluster_members`, `derived_meta`. Prints the metadata including `content_hash` (identical on identical input; reference: `5e60fa2baadaaebeda97c75b6f2f5720367ffecdc7b4ae514d69519b889becd6`), `spatial_method`, `cluster_threshold_m`, `headsigns_available`, `built_at`, `source_fingerprint`.
* **Run it again after every `import_gtfs`** (the import replaces the file). Safe to run any number of times; a failed run leaves the previous derived data in place.
* Without it: `/stops/nearby` uses `index: "scan"` (correct, slower), smart search works without clusters, `cluster_id` is absent and `/clusters/{id}` → 503 `derived_data_missing`.
* Check state: `sqlite3 data/crowdsense.sqlite3 "select * from derived_meta"`.

## 3. Environment variables
| Where | Variable | Default | Meaning |
|---|---|---|---|
| frontend | `VITE_MAP_STYLE_URL` | *(empty)* | MapLibre style JSON URL (https; http only for localhost). Empty → plain background with the route and stops, and a visible notice. **No default tile provider by design.** |
| frontend | `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | unchanged |
| backend | all Phase 3 variables | | unchanged. Phase 4 adds none. Alias CSVs live in `backend/data/aliases/`. |

## 4. Tile provider setup (when you are ready to show a street map)
1. Pick a provider whose terms allow your traffic (not `tile.openstreetmap.org`; see ADR-02) or self-host vector tiles. Record its rate limits and cost.
2. Create a key **restricted to your site's domain(s)** (HTTP referrer). The key is embedded in the style URL and is visible to every visitor; restriction is the only protection. Never commit it: put it in `frontend/.env.local` (git-ignored) or the build environment:
   `VITE_MAP_STYLE_URL=https://provider.example/styles/streets/style.json?key=…`
3. Rebuild (`npm run build`; Vite inlines the value at build time).
4. Confirm on screen: tiles load, the provider's attribution text appears bottom-right next to "Route and stop data: Delhi GTFS", and with the network blocked the map falls back to the plain background with "Street tiles could not be loaded".
5. Failure behaviour you get for free: no style → plain map + notice; tile/style error → plain map + warning; no WebGL → "Map unavailable" card listing the stops.

## 5. Privacy notes
* User coordinates exist only in the browser and in the `lat`/`lon` query of `GET /stops/nearby` to **your own** backend. The backend does not store them, and the `uvicorn.access`/`uvicorn.error`/`app` loggers redact `lat`, `lon`, `latitude`, `longitude`, `lng` values (`GET /api/v1/stops/nearby?lat=[redacted]&lon=[redacted]&…`). If you put a reverse proxy, CDN or WAF in front, **its** access log will contain the query string: disable or redact it there (this repository cannot).
* They are never sent to a tile provider or analytics (there is none). The provider can see which tiles are fetched (the general area).
* Geolocation is requested only after clicking "Use my location". The position is never persisted (URL, localStorage, cookies).
* Saved/recent places: `localStorage` key `crowdsense.places.v1`, stop ids only, ≤ 10 saved + ≤ 20 recent, labelled "stored on this device only", deletable one by one or all at once.
* Known pre-existing third-party request: Google Fonts (G13).
* Verify after any change: `python -m pytest tests/test_nearby.py -k "real_server_logs or redaction"`.

## 6. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Map card says "No street basemap is configured" | expected without `VITE_MAP_STYLE_URL` |
| "Map unavailable … needs WebGL" | browser/GPU without WebGL; the stop list below the card has the same information |
| Search shows no groups / `cluster_id` missing | derived data not built → §2 |
| `/stops/nearby` → 422 `location_out_of_area` | point outside 28.00–29.50 N, 76.40–77.80 E |
| Alias file ignored | see the ERROR log line `alias files rejected`; fix the CSV (every row needs `source`, `added_by`, `added_on` and an existing id) |
| CORS error in the browser | the frontend must be on `localhost:5173` or `127.0.0.1:5173` |

## 7. Browser QA checklist (NOT yet done: see GAPS G1)
Pages × viewports (375 and 1440 px at minimum, also 320/768/1024): `/` · `/nearby` · `/journeys?...` · `/journeys/72_06_40?from=106&to=216&date=2026-11-11&board=06:56:26` · `/routes/72` · `/stops/106`.
For each: console errors = 0; failed requests = only intentional ones; no horizontal scroll at 320 px; map renders route line + markers; hover/focus on a timeline stop highlights the marker and vice-versa; the sheet drags and its handle works with the keyboard; zoom/reset buttons work; with DevTools "Offline" the fallbacks appear; with a style URL the attribution is visible; with "Fast 3G" throttling the map is interactive in < 1.5 s; panning a 5,000-stop layer shows no long task > 200 ms (Performance panel).
