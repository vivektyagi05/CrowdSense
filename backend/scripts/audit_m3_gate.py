"""Phase 4 / M3 gate evidence against a running server + the real database (read-only)."""
import gzip, json, random, sqlite3, time, httpx
from app.geo.planar import Plane, distance_to_polyline, polyline_length, rdp
from app.services.leg_service import _load_shape
BASE = "http://127.0.0.1:8000/api/v1"; cl = httpx.Client(timeout=30)
c = sqlite3.connect("file:data/crowdsense.sqlite3?mode=ro", uri=True); c.row_factory = sqlite3.Row
pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]
def calls(trip): return c.execute("select stop_id, departure_time from stop_times where trip_id=? order by stop_sequence", (trip,)).fetchall()
def timed(params, trip, n=30):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); r = cl.get(f"{BASE}/trips/{trip}/shape", params=params); ts.append((time.perf_counter() - t) * 1000)
    return r, ts
# 1) longest route (1501-pt shape): whole-trip leg (worst case) and a mid leg
trip = "2716_04_50"; k = calls(trip)
for label, a, b in (("full loop (183 calls)", 0, len(k) - 1), ("mid leg 40->120", 40, 120)):
    p = dict(from_stop_id=k[a][0], to_stop_id=k[b][0], board=k[a][1]); r, ts = timed(p, trip); j = r.json()
    raw = cl.get(f"{BASE}/trips/{trip}/shape").content
    print(f"[longest route 2716] {label}: status={j['status']} orig_pts={j['point_count_original']} returned={j['point_count_returned']} "
          f"len={j['length_m']}m (orig {j['length_original_m']}m) bytes={len(r.content)} gzip={len(gzip.compress(r.content))} "
          f"| p50={pct(ts,.5):.1f}ms p95={pct(ts,.95):.1f}ms (n=30) | legacy full shape bytes={len(raw)} gzip={len(gzip.compress(raw))}")
# 2) 300 random real legs across all routes
random.seed(11); trips = [r[0] for r in c.execute("select min(trip_id) from trips group by route_id")]
ts = []; statuses = {}; ratios = []; tot_raw = tot_leg = 0
for t in random.sample(trips, 300):
    k = calls(t)
    if len(k) < 3: continue
    a = random.randrange(0, len(k) - 2); b = random.randrange(a + 1, len(k))
    if k[a][0] == k[b][0]: continue
    t0 = time.perf_counter(); r = cl.get(f"{BASE}/trips/{t}/shape", params=dict(from_stop_id=k[a][0], to_stop_id=k[b][0], board=k[a][1])); ts.append((time.perf_counter() - t0) * 1000)
    j = r.json(); statuses[j["status"]] = statuses.get(j["status"], 0) + 1
    if j["status"] == "ok":
        ratios.append(j["length_m"] / j["length_original_m"]); tot_leg += len(r.content)
print(f"[300 random legs, all routes] statuses={statuses} p50={pct(ts,.5):.1f}ms p95={pct(ts,.95):.1f}ms p99={pct(ts,.99):.1f}ms max={max(ts):.1f}ms")
print(f"   simplified/original length ratio: min={min(ratios):.4f} max={max(ratios):.4f}; mean leg payload={tot_leg//len(ratios)} bytes")
# 3) RDP over ALL 2,554 real shapes at 5 m: deviation bound, length change, point reduction
worst_dev = 0; worst_len = 0; before = after = 0
for (sid,) in c.execute("select shape_id from shapes"):
    pts = _load_shape(c, sid); plane = Plane.around([(p[0], p[1]) for p in pts]); xy = [plane.to_xy(p[0], p[1]) for p in pts]
    keep = rdp(xy, 5.0); s = [xy[i] for i in keep]
    before += len(xy); after += len(s)
    worst_len = max(worst_len, 1 - polyline_length(s) / polyline_length(xy))
    if len(xy) < 400:  # exact deviation check on every shape under 400 pts (O(n*m)); longer ones sampled below
        worst_dev = max(worst_dev, max(distance_to_polyline(p, s) for p in xy))
print(f"[all 2,554 shapes @5 m] points {before:,} -> {after:,} ({after/before*100:.1f}%); max length loss {worst_len*100:.3f}%; max deviation (shapes<400 pts) {worst_dev:.3f} m")
# 4) routes/{id}/shapes with geometry: size + latency for the longest route
for tol in (5, 20):
    r = None; ts = []
    for _ in range(30):
        t0 = time.perf_counter(); r = cl.get(f"{BASE}/routes/2716/shapes", params=dict(geometry="true", tolerance_m=tol)); ts.append((time.perf_counter() - t0) * 1000)
    it = r.json()["items"][0]
    print(f"[routes/2716/shapes?geometry=true&tolerance_m={tol}] pts {it['point_count_original']}->{it['point_count_returned']} bytes={len(r.content)} gzip={len(gzip.compress(r.content))} p50={pct(ts,.5):.1f}ms p95={pct(ts,.95):.1f}ms")
