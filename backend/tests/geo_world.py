"""Synthetic road world for geometry tests. Test-only data (labelled SYNTHETIC in docs/phase4/EVIDENCE.md)."""
from __future__ import annotations

LAT0, LON0 = 28.60, 77.20


def _shape(shape_id: str, pts: list[tuple[float, float]], dist: bool = True, bad_dist: bool = False) -> str:
    rows, acc = [], 0.0
    for i, (la, lo) in enumerate(pts):
        d = ""
        if dist:
            d = f"{(acc if not (bad_dist and i == 3) else acc + 5000):.1f}"
        rows.append(f"{shape_id},{la:.6f},{lo:.6f},{i},{d}")
        acc += 100.0
    return "\n".join(rows) + "\n"


def line_pts():       # straight east-west road, 11 points, ~98 m apart
    return [(LAT0, LON0 + i * 0.001) for i in range(11)]


def rect_pts():       # closed rectangle, clockwise, with intermediate points
    p = [(LAT0, LON0 + i * 0.002) for i in range(6)]
    p += [(LAT0 + j * 0.002, LON0 + 0.010) for j in range(1, 6)]
    p += [(LAT0 + 0.010, LON0 + 0.010 - i * 0.002) for i in range(1, 6)]
    p += [(LAT0 + 0.010 - j * 0.002, LON0) for j in range(1, 6)]
    return p


def out_back_pts():   # out along the road and back along the very same road
    out = line_pts()
    return out + out[-2::-1]


STOPS = {
    # straight line, 0.0001 deg (~11 m) north of the road
    **{f"S{i}": (LAT0 + 0.0001, LON0 + 0.002 * i) for i in range(6)},
    # rectangle stops (on the loop); L8 is L0 again (same stop id)
    "L0": (LAT0, LON0), "L1": (LAT0, LON0 + 0.005), "L2": (LAT0, LON0 + 0.010), "L3": (LAT0 + 0.005, LON0 + 0.010),
    "L4": (LAT0 + 0.010, LON0 + 0.010), "L5": (LAT0 + 0.010, LON0 + 0.005), "L6": (LAT0 + 0.010, LON0),
    "L7": (LAT0 + 0.005, LON0),
    # out-and-back stops on the straight road
    "X0": (LAT0, LON0), "X1": (LAT0, LON0 + 0.005), "X2": (LAT0, LON0 + 0.010),
    # ~550 m north of the road: not on any shape
    "FAR": (LAT0 + 0.005, LON0 + 0.004),
}


def _calls(trip: str, stop_ids: list[str], start_min: int = 0, dists: list[float | None] | None = None) -> str:
    rows = []
    for i, s in enumerate(stop_ids):
        t = start_min + i * 2
        hh, mm = divmod(t, 60)
        d = "" if dists is None or dists[i] is None else str(dists[i])
        rows.append(f"{trip},{hh + 8:02d}:{mm:02d}:00,{hh + 8:02d}:{mm:02d}:00,{s},{i + 1},{d}")
    return "\n".join(rows) + "\n"


def feed() -> dict[str, str]:
    stops = "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(f"{k},Stop {k},{la:.6f},{lo:.6f}\n" for k, (la, lo) in STOPS.items())
    trips = [("RLINE", "T_LINE", "SH_LINE"), ("RLOOP", "T_LOOP", "SH_LOOP"), ("RBACK", "T_BACK", "SH_BACK"),
             ("RNOSH", "T_NOSHAPE", ""), ("RFAR", "T_FAR", "SH_LINE"), ("RDIST", "T_DIST_OK", "SH_LINE"),
             ("RUNIT", "T_DIST_UNIT", "SH_LINE")]
    shapes = (_shape("SH_LINE", line_pts()) + _shape("SH_LOOP", rect_pts(), dist=False) + _shape("SH_BACK", out_back_pts(), dist=False)
             )
    line_stop_dist = [0.0, 200.0, 400.0, 600.0, 800.0, 1000.0]       # shape dist is 100 per point (0.002 deg = 2 points)
    st = (_calls("T_LINE", [f"S{i}" for i in range(6)])
          + _calls("T_LOOP", ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L0"])
          + _calls("T_BACK", ["X0", "X1", "X2", "X1", "X0"])
          + _calls("T_NOSHAPE", ["S0", "S1"])
          + _calls("T_FAR", ["S0", "FAR", "S5"])
          + _calls("T_DIST_OK", [f"S{i}" for i in range(6)], dists=line_stop_dist)
          + _calls("T_DIST_UNIT", [f"S{i}" for i in range(6)], dists=[d * 1000 for d in line_stop_dist]))
    return {
        "stops.txt": stops,
        "routes.txt": "route_id,route_short_name,route_long_name,route_type\n" + "".join(f"{r},{r},{r},3\n" for r, _, _ in trips),
        "trips.txt": "route_id,service_id,trip_id,shape_id\n" + "".join(f"{r},S1,{t},{s}\n" for r, t, s in trips),
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,shape_dist_traveled\n" + st,
        "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence,shape_dist_traveled\n" + shapes,
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS1,1,1,1,1,1,1,1,20250101,20401231\n",
    }
