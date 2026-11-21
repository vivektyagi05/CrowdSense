"""Phase 4 / M1 read-only data audit. Prints facts; never writes to the database."""
from __future__ import annotations
import math, sqlite3, sys, unicodedata, re
from collections import Counter, defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "data/crowdsense.sqlite3"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchall()
one = lambda s, *a: c.execute(s, a).fetchone()[0]

def norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"[\(\)\[\]\{\}.,;:'\"`!?/\\|*_-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def hav(a, b):
    R = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

print("== counts")
for t in ("stops","routes","trips","stop_times","shapes","shape_points"):
    print(t, one(f"select count(*) from {t}"))

print("\n== stops: coordinates")
print("null coords:", one("select count(*) from stops where stop_lat is null or stop_lon is null"))
print("zero coords:", one("select count(*) from stops where stop_lat=0 or stop_lon=0"))
print("lat/lon min/max:", q("select min(stop_lat),max(stop_lat),min(stop_lon),max(stop_lon) from stops"))
# Delhi-NCR generous box 28.0-29.1 N, 76.6-77.8 E (audit box; ADR in M4 decides final)
BOX=(28.0,29.1,76.6,77.8)
print("outside audit box", BOX, ":", one("select count(*) from stops where stop_lat not between ? and ? or stop_lon not between ? and ?", *BOX))
print("outside strict Delhi bbox (28.40-28.90N,76.84-77.35E):", one("select count(*) from stops where stop_lat not between 28.40 and 28.90 or stop_lon not between 76.84 and 77.35"))
print("stops with no stop_times (no routes):", one("select count(*) from stops s where not exists(select 1 from stop_times st where st.stop_id=s.stop_id)"))
print("empty/null stop_name:", one("select count(*) from stops where stop_name is null or trim(stop_name)=''"))
print("location_type values:", q("select location_type,count(*) from stops group by 1"))
print("parent_station non-null:", one("select count(*) from stops where parent_station is not null"))

stops = q("select stop_id,stop_name,stop_lat,stop_lon from stops where stop_lat is not null")
byname = defaultdict(list)
for sid, name, la, lo in stops:
    byname[norm(name)].append((sid, la, lo))
raw_distinct = len({n for _, n, *_ in stops})
print("\n== names")
print("distinct raw names:", raw_distinct, " distinct normalised:", len(byname))
multi = {k: v for k, v in byname.items() if len(v) > 1}
print("normalised names shared by >1 stop:", len(multi), " stops involved:", sum(len(v) for v in multi.values()))
print("name-group size histogram:", sorted(Counter(len(v) for v in byname.values()).items()))
print("exact duplicate coordinates (pairs sharing lat/lon):", one("select count(*) from (select 1 from stops group by stop_lat,stop_lon having count(*)>1)"))

def complete_linkage(members, thr):
    """Deterministic greedy complete-linkage: process by stop_id, join first cluster where ALL members <= thr."""
    clusters = []
    for sid, la, lo in sorted(members):
        for cl in clusters:
            if all(hav((la, lo), (m[1], m[2])) <= thr for m in cl):
                cl.append((sid, la, lo)); break
        else:
            clusters.append([(sid, la, lo)])
    return clusters

print("\n== cluster size histograms (same normalised name + complete linkage), by threshold")
for thr in (50, 100, 150, 250, 400):
    sizes = Counter()
    for k, v in byname.items():
        for cl in complete_linkage(v, thr):
            sizes[len(cl)] += 1
    nclu = sum(sizes.values())
    print(f"{thr:>4} m: clusters={nclu} multi-stop={sum(n for s,n in sizes.items() if s>1)} hist={sorted(sizes.items())}")

print("\n== pairwise-distance distribution inside same-name groups (nearest neighbour per stop, m)")
nn = []
for k, v in multi.items():
    for i, a in enumerate(v):
        nn.append(min(hav((a[1], a[2]), (b[1], b[2])) for j, b in enumerate(v) if j != i))
nn.sort()
def pct(p): return round(nn[min(len(nn)-1, int(p*len(nn)))], 1)
print("n=", len(nn), "p10", pct(.1), "p25", pct(.25), "p50", pct(.5), "p75", pct(.75), "p90", pct(.9), "p95", pct(.95))
bins = [0,25,50,75,100,150,200,250,400,800,1600,5000,1e9]
cnt = Counter()
for d in nn:
    for lo, hi in zip(bins, bins[1:]):
        if lo <= d < hi: cnt[f"{lo}-{hi}"] += 1
print("nearest-same-name distance bins:", dict(cnt))

print("\n== shapes")
print("shapes with <2 points:", one("select count(*) from shapes where point_count<2"))
print("point_count column vs actual mismatch:", one("select count(*) from shapes s where point_count <> (select count(*) from shape_points p where p.shape_id=s.shape_id)"))
print("trips total / with shape_id null:", one("select count(*) from trips"), one("select count(*) from trips where shape_id is null"))
print("trips whose shape_id not in shapes:", one("select count(*) from trips where shape_id is not null and shape_id not in (select shape_id from shapes)"))
print("distinct shapes used by trips:", one("select count(distinct shape_id) from trips"))
print("shapes unused by any trip:", one("select count(*) from shapes where shape_id not in (select shape_id from trips where shape_id is not null)"))
print("shape points with dist_traveled NOT NULL:", one("select count(*) from shape_points where shape_dist_traveled is not null"), "of", one("select count(*) from shape_points"))
print("max point_count / avg point_count:", q("select max(point_count), round(avg(point_count),1) from shapes"))
print("stop_times shape_dist_traveled NOT NULL:", one("select count(*) from stop_times where shape_dist_traveled is not null"))
print("stop_times stop_dist NOT NULL (non-GTFS col):", one("select count(*) from stop_times where stop_dist is not null"))

# ordering + monotonicity of shape_dist_traveled and sequence gaps; python scan
nonmono = 0; unordered = 0; dup_seq = 0; nodist = 0
rows = c.execute("select shape_id, shape_pt_sequence, shape_dist_traveled, shape_pt_lat, shape_pt_lon from shape_points order by shape_id, rowid")
cur = None; last_seq = None; last_d = None
bad_shapes_nonmono=set(); bad_shapes_unordered=set()
for sid, seq, d, la, lo in rows:
    if sid != cur: cur, last_seq, last_d = sid, None, None
    if last_seq is not None and seq <= last_seq: bad_shapes_unordered.add(sid)
    if d is not None and last_d is not None and d < last_d: bad_shapes_nonmono.add(sid)
    last_seq, last_d = seq, (d if d is not None else last_d)
print("shapes whose rowid order != sequence order:", len(bad_shapes_unordered))
print("shapes with decreasing shape_dist_traveled (in sequence order):", len(bad_shapes_nonmono))
# by sequence order (what the API uses)
bad=set(); cur=None; last=None
for sid, d in c.execute("select shape_id, shape_dist_traveled from shape_points order by shape_id, shape_pt_sequence"):
    if sid!=cur: cur,last=sid,None
    if d is not None:
        if last is not None and d < last: bad.add(sid)
        last=d
print("shapes with decreasing shape_dist_traveled by sequence order:", len(bad))
print("shapes with all-null shape_dist_traveled:", one("select count(*) from (select shape_id from shape_points group by shape_id having count(shape_dist_traveled)=0)"))

print("\n== trips / stop_times")
print("trips with <2 stop_times:", one("select count(*) from (select trip_id from stop_times group by trip_id having count(*)<2)"))
print("trips with duplicate stop (loop/repeat) :", one("select count(*) from (select trip_id from stop_times group by trip_id having count(*)<>count(distinct stop_id))"))
print("routes with >1 distinct shape:", one("select count(*) from (select route_id from trips group by route_id having count(distinct shape_id)>1)"))
print("headsign null/empty trips:", one("select count(*) from trips where trip_headsign is null or trim(trip_headsign)=''"))
print("direction_id values:", q("select direction_id,count(*) from trips group by 1"))
print("stop_headsign non-null in stop_times:", one("select count(*) from stop_times where stop_headsign is not null and trim(stop_headsign)<>''"))
