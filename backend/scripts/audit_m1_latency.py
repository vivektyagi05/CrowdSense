"""Phase 4 / M1: latency + size of existing endpoints against a running server (read-only)."""
import gzip, json, random, sqlite3, statistics, sys, time, httpx
BASE = "http://127.0.0.1:8000/api/v1"
c = sqlite3.connect("file:data/crowdsense.sqlite3?mode=ro", uri=True)
cl = httpx.Client(timeout=30)
def pct(xs, p): xs = sorted(xs); return xs[min(len(xs)-1, int(round(p*(len(xs)-1))))]
def bench(label, url, n=30, params=None):
    ts = []; size = None
    for _ in range(n):
        t = time.perf_counter(); r = cl.get(url, params=params); ts.append((time.perf_counter()-t)*1000)
        size = len(r.content); assert r.status_code == 200, (r.status_code, r.text[:200])
    print(f"{label:<44} status=200 bytes={size:>8} gzip={len(gzip.compress(r.content)):>7} p50={pct(ts,.5):6.1f}ms p95={pct(ts,.95):6.1f}ms n={n}")
long_route = c.execute("select t.route_id, t.trip_id, s.shape_id, s.point_count from shapes s join trips t using(shape_id) order by s.point_count desc limit 1").fetchone()
med = c.execute("select point_count from shapes order by point_count limit 1 offset 1277").fetchone()[0]
typ = c.execute("select t.route_id, t.trip_id, s.shape_id, s.point_count from shapes s join trips t using(shape_id) where s.point_count=? limit 1", (med,)).fetchone()
print("longest:", long_route, " typical:", typ)
for name, (rid, tid, sid, pc) in (("longest", long_route), ("typical", typ)):
    bench(f"GET /trips/{{id}}/shape [{name}, {pc} pts]", f"{BASE}/trips/{tid}/shape")
    bench(f"GET /trips/{{id}}/shape?format=geojson [{name}]", f"{BASE}/trips/{tid}/shape", params={"format": "geojson"})
    bench(f"GET /routes/{{id}}/shapes [{name}]", f"{BASE}/routes/{rid}/shapes")
    bench(f"GET /shapes/{{id}} [{name}]", f"{BASE}/shapes/{sid}")
bench("GET /stops/{id} (detail)", f"{BASE}/stops/" + c.execute("select stop_id from stops limit 1").fetchone()[0])
# search: 100 mixed queries
names = [r[0] for r in c.execute("select stop_name from stops")]
random.seed(7)
qs = []
for _ in range(100):
    n = random.choice(names); k = random.choice([3, 4, 6, 9])
    s = random.randrange(0, max(1, len(n)-k)); qs.append(n[s:s+k].strip() or "ka")
qs = [q if len(q) >= 2 else "ka" for q in qs]
ts = []
for q in qs:
    t = time.perf_counter(); r = cl.get(f"{BASE}/stops", params={"q": q, "limit": 20}); ts.append((time.perf_counter()-t)*1000); assert r.status_code == 200
print(f"GET /stops?q= (100 mixed substring queries)   p50={pct(ts,.5):.1f}ms p95={pct(ts,.95):.1f}ms max={max(ts):.1f}ms")
print("sample query/total/size:", [(q, cl.get(f'{BASE}/stops', params={'q': q}).json()['total']) for q in qs[:5]])
# typos: what the current search does with a typo
for q in ("kashmire gate", "kashmere gate", "Kashmere  Gate", "कश्मीरी गेट", "gate kashmere"):
    r = cl.get(f"{BASE}/stops", params={"q": q}); print(f"current search {q!r:<20} -> total={r.json().get('total')}")
