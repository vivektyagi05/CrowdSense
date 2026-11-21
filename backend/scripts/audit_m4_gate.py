"""Phase 4 / M4 gate on the REAL data: brute-force oracle (200 random points), latency, index method. Needs a derived-built DB."""
import random, sqlite3, sys, time, httpx
from app.geo.planar import haversine_m
DB = sys.argv[1]; BASE = "http://127.0.0.1:8000/api/v1"; cl = httpx.Client(timeout=30)
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
stops = c.execute("select stop_id, stop_lat, stop_lon from stops").fetchall()
print("index method:", c.execute("select value from derived_meta where key='spatial_method'").fetchone()[0])
print("all stops inside NCR box:", all(28.0 <= la <= 29.5 and 76.4 <= lo <= 77.8 for _, la, lo in stops))
rnd = random.Random(2026); ok = nonempty = 0; ts = []; log_probe = []
for i in range(200):
    if i % 2: sid, la, lo = rnd.choice(stops); lat, lon = la + rnd.uniform(-.004, .004), lo + rnd.uniform(-.004, .004)   # near real stops
    else: lat, lon = rnd.uniform(28.45, 28.88), rnd.uniform(76.9, 77.35)
    radius, limit = rnd.choice([50, 150, 300, 500, 1000, 3000]), rnd.choice([1, 5, 20, 50])
    t = time.perf_counter(); r = cl.get(f"{BASE}/stops/nearby", params=dict(lat=lat, lon=lon, radius_m=radius, limit=limit)); ts.append((time.perf_counter() - t) * 1000)
    j = r.json(); log_probe.append((lat, lon))
    hits = sorted((haversine_m(lat, lon, a, b), s) for s, a, b in stops if haversine_m(lat, lon, a, b) <= radius)
    exp = [s for _, s in hits[:limit]]
    assert [x["stop_id"] for x in j["items"]] == exp and j["total_in_radius"] == len(hits), (lat, lon, radius, limit)
    ok += 1; nonempty += bool(exp)
print(f"oracle: {ok}/200 identical (set + order); non-empty results in {nonempty}/200")
# latency: 500 requests, typical urban params
ts = []
for _ in range(500):
    sid, la, lo = rnd.choice(stops)
    t = time.perf_counter(); r = cl.get(f"{BASE}/stops/nearby", params=dict(lat=la, lon=lo, radius_m=500, limit=20)); ts.append((time.perf_counter() - t) * 1000)
ts.sort(); print(f"latency (500 req, radius 500, limit 20): p50={ts[250]:.1f}ms p95={ts[475]:.1f}ms p99={ts[495]:.1f}ms max={ts[-1]:.1f}ms")
ts = []
for _ in range(100):
    sid, la, lo = rnd.choice(stops)
    t = time.perf_counter(); r = cl.get(f"{BASE}/stops/nearby", params=dict(lat=la, lon=lo, radius_m=3000, limit=50)); ts.append((time.perf_counter() - t) * 1000)
ts.sort(); print(f"latency worst-case params (100 req, radius 3000, limit 50): p50={ts[50]:.1f}ms p95={ts[95]:.1f}ms max={ts[-1]:.1f}ms")
open("/tmp/probe_coords.txt", "w").write("\n".join(f"{a!r} {b!r}" for a, b in log_probe))
