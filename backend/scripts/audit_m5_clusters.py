"""Phase 4 / M5 statistics report on a derived-built database (read-only)."""
import random, sqlite3, sys
from collections import Counter
from app.geo.planar import haversine_m
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); c.row_factory = sqlite3.Row
meta = dict(c.execute("select key, value from derived_meta").fetchall())
print({k: meta[k] for k in ("cluster_rule", "cluster_threshold_m", "cluster_count", "stop_count", "content_hash", "headsigns_available")})
members = {}
for r in c.execute("select cm.cluster_id, s.stop_id, s.stop_name, s.stop_lat, s.stop_lon from cluster_members cm join stops s using(stop_id) order by 1, 2"):
    members.setdefault(r["cluster_id"], []).append(r)
sizes = Counter(len(v) for v in members.values())
print("clusters:", len(members), "| size histogram:", sorted(sizes.items()), "| stops in multi-stop clusters:", sum(n * k for k, n in sizes.items() if k > 1))
print("every stop in exactly one cluster:", c.execute("select count(*), count(distinct stop_id) from cluster_members").fetchone()[:], "of", c.execute("select count(*) from stops").fetchone()[0])
def spread(v): return max((haversine_m(a["stop_lat"], a["stop_lon"], b["stop_lat"], b["stop_lon"]) for a in v for b in v), default=0)
def routes(sid): return [r[0] for r in c.execute("select r.route_short_name from stop_routes sr join routes r using(route_id) where sr.stop_id=? order by sr.call_count desc limit 4", (sid,))]
print("\nLargest 10 clusters (by members, then spread):")
for cid, v in sorted(members.items(), key=lambda kv: (-len(kv[1]), -spread(kv[1])))[:10]:
    print(f"  {cid} '{v[0]['stop_name']}' n={len(v)} max-pairwise={spread(v):.0f}m members={[x['stop_id'] for x in v]}")
print("\n20 random multi-stop clusters (seed 5):")
rnd = random.Random(5); multi = sorted(k for k, v in members.items() if len(v) > 1)
for cid in rnd.sample(multi, 20):
    v = members[cid]; print(f"  {cid} '{v[0]['stop_name']}' n={len(v)} spread={spread(v):.0f}m | " + " | ".join(f"{x['stop_id']}:{','.join(routes(x['stop_id']))}" for x in v))
wide = [(cid, spread(v)) for cid, v in members.items() if len(v) > 1 and spread(v) > 120]
print(f"\nmulti-stop clusters with spread > 120 m (review list): {len(wide)}")
share = sum(1 for cid in multi if not set(routes(members[cid][0]['stop_id'])) & set(routes(members[cid][-1]['stop_id']))) 
print("multi-stop clusters whose first/last member share none of their top-4 routes (typical for opposite sides):", share, "of", len(multi))
