"""Phase 4 / M6 gate: smart-search latency (200 mixed real-name queries) against a running server; cold vs warm."""
import random, sqlite3, time, httpx
from app.derived.names import normalise
BASE = "http://127.0.0.1:8000/api/v1"; cl = httpx.Client(timeout=30)
c = sqlite3.connect("file:data/crowdsense.sqlite3?mode=ro", uri=True)
names = sorted({normalise(r[0]) for r in c.execute("select stop_name from stops")})
rnd = random.Random(8); qs = []; kinds = []
for _ in range(200):
    n = rnd.choice(names); toks = n.split(); k = rnd.choice(["exact", "prefix", "typo", "reorder", "partial", "substring"])
    q = {"exact": n, "prefix": n[:max(3, len(n)//2)], "typo": (n[:3] + n[4:]) if len(n) > 6 else n, "reorder": " ".join(reversed(toks)),
         "partial": toks[0], "substring": n[len(n)//3: len(n)//3 + 5]}[k]
    qs.append(q if len(q.strip()) >= 2 else "ka"); kinds.append(k)
t = time.perf_counter(); cl.get(f"{BASE}/stops", params=dict(q="warm", mode="smart")); print(f"first request after startup (index pre-warmed by lifespan): {(time.perf_counter()-t)*1000:.1f} ms")
ts = []
for q in qs:
    t = time.perf_counter(); r = cl.get(f"{BASE}/stops", params=dict(q=q, mode="smart", limit=20)); ts.append((time.perf_counter() - t) * 1000); assert r.status_code == 200
s = sorted(ts); print(f"smart search, 200 queries: p50={s[100]:.1f}ms p95={s[189]:.1f}ms p99={s[197]:.1f}ms max={s[-1]:.1f}ms")
ts2 = []
for q in qs[:100]:
    t = time.perf_counter(); cl.get(f"{BASE}/stops", params=dict(q=q, limit=20)); ts2.append((time.perf_counter() - t) * 1000)
s2 = sorted(ts2); print(f"existing substring mode, same 100 queries: p50={s2[50]:.1f}ms p95={s2[94]:.1f}ms")
j = cl.get(f"{BASE}/stops", params=dict(q="kashmere gate", mode="smart", limit=20)); print("response bytes (kashmere gate, limit 20):", len(j.content))
