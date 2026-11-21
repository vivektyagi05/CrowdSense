"""Phase 4 / M3 evidence: how far are real stops from their route's shape? (read-only, all 2,554 routes)"""
import sqlite3, statistics, sys, time
from app.geo.planar import Plane, PolylineIndex, monotone_match
from app.services.leg_service import _load_calls, _load_shape
c = sqlite3.connect("file:data/crowdsense.sqlite3?mode=ro", uri=True); c.row_factory = sqlite3.Row
trips = c.execute("select route_id, min(trip_id) trip_id, shape_id from trips group by route_id").fetchall()
BIG = 500.0
dists = []; unmatched60 = 0; calls_total = 0; routes_with_unmatched = 0; broken = 0; times = []
worst = []
for t in trips:
    pts = _load_shape(c, t["shape_id"]); calls = _load_calls(c, t["trip_id"])
    t0 = time.perf_counter()
    plane = Plane.around([(p[0], p[1]) for p in pts]); line = [plane.to_xy(p[0], p[1]) for p in pts]
    idx = PolylineIndex(line, reach_m=BIG)
    m = monotone_match(idx, [plane.to_xy(x["stop_lon"], x["stop_lat"]) for x in calls], BIG)
    times.append((time.perf_counter() - t0) * 1000)
    miss = 0
    for x, cand in zip(calls, m):
        calls_total += 1
        if cand is None: miss += 1; unmatched60 += 1; continue
        dists.append(cand.dist_m)
    if miss: routes_with_unmatched += 1
    along = [cand.along_m for cand in m if cand]
    if any(b < a - 1.0 for a, b in zip(along, along[1:])): broken += 1
    worst.append((max((cand.dist_m for cand in m if cand), default=0), t["route_id"]))
dists.sort(); q = lambda p: round(dists[int(p * (len(dists) - 1))], 1)
print(f"routes={len(trips)} stop-calls={calls_total} matched<=500m={len(dists)} unmatched(>500m)={unmatched60}")
print("distance stop->matched shape point (m): p50", q(.5), "p90", q(.9), "p95", q(.95), "p99", q(.99), "p99.9", q(.999), "max", q(1))
for thr in (20, 30, 40, 60, 80, 100, 150):
    print(f"  share of stop-calls within {thr:>3} m: {sum(1 for d in dists if d <= thr)/calls_total*100:.2f}%")
print("routes whose matched positions are not monotone:", broken)
print("routes with any stop >500 m from shape:", routes_with_unmatched)
print("worst 5 routes (max matched distance m):", sorted(worst, reverse=True)[:5])
times.sort()
print(f"projection time per full trip (ms): p50 {times[len(times)//2]:.1f} p95 {times[int(len(times)*.95)]:.1f} max {times[-1]:.1f}")
