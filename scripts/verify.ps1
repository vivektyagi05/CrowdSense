<#
 Local verification (Phase 0 + Phase 1) (Windows PowerShell). Run from the repository root:
     powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
 Never touches your real database: tests use temporary databases, and the GTFS
 import step is --validate-only.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== Backend tests ==" -ForegroundColor Cyan
Push-Location "$root\backend"
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt --disable-pip-version-check
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "backend tests failed" }

if (Test-Path data\delhi_buses_static_gtfs_v1.zip) {
    Write-Host "== GTFS validation (database untouched) ==" -ForegroundColor Cyan
    .\.venv\Scripts\python.exe -m scripts.import_gtfs --validate-only
    if ($LASTEXITCODE -ne 0) { throw "GTFS validation failed" }
    Write-Host "== Real-feed integration test (temporary database) ==" -ForegroundColor Cyan
    $env:CROWDSENSE_REAL_FEED_ZIP = (Resolve-Path data\delhi_buses_static_gtfs_v1.zip).Path
    .\.venv\Scripts\python.exe -m pytest -m real_feed -q
    if ($LASTEXITCODE -ne 0) { throw "real-feed integration test failed" }
    Remove-Item Env:CROWDSENSE_REAL_FEED_ZIP
} else { Write-Host "GTFS ZIP not found in backend\data - skipping import validation" -ForegroundColor Yellow }
Pop-Location

Write-Host "== Frontend tests + production build ==" -ForegroundColor Cyan
Push-Location "$root\frontend"
npm ci
npm test
if ($LASTEXITCODE -ne 0) { throw "frontend tests failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Pop-Location
Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
