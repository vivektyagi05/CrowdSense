"""Nearby stops: bounding-box prefilter (R-tree / grid / plain scan) + exact haversine + deterministic sort."""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from app.errors import AppError
from app.geo.planar import EARTH_RADIUS_M, haversine_m

# Expanded Delhi-NCR validation box (ADR-02). Contains all 6,812 stops (lat 28.208-29.342, lon 76.601-77.431).
NCR_BOX = {"min_lat": 28.00, "max_lat": 29.50, "min_lon": 76.40, "max_lon": 77.80}
RADIUS_MIN, RADIUS_MAX, RADIUS_DEFAULT = 50, 3000, 500
LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1, 50, 20
ROUTE_NAMES_CAP = 5
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
GRID_CELL_DEG = 0.005


def validate_point(lat: float, lon: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise AppError(422, "validation_error", "lat and lon must be finite numbers.")
    b = NCR_BOX
    if not (b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]):
        raise AppError(422, "location_out_of_area",
                       f"This location is outside the Delhi-NCR service area ({b['min_lat']}-{b['max_lat']} N, "
                       f"{b['min_lon']}-{b['max_lon']} E). CrowdSense only has Delhi bus data.")


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass(deg: float) -> str:
    return _COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def spatial_method(conn: sqlite3.Connection) -> str:
    """'rtree' | 'grid' (derived tables built) | 'scan' (derived data not built: plain bbox scan, still correct)."""
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'derived_meta'").fetchone()
    if row is None:
        return "scan"
    m = conn.execute("SELECT value FROM derived_meta WHERE key = 'spatial_method'").fetchone()
    return m[0] if m else "scan"


def _candidates(conn: sqlite3.Connection, lat: float, lon: float, radius_m: float, method: str) -> list[sqlite3.Row]:
    dlat = math.degrees(radius_m / EARTH_RADIUS_M) * 1.001 + 1e-5
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    lo_lat, hi_lat, lo_lon, hi_lon = lat - dlat, lat + dlat, lon - dlon, lon + dlon
    cols = "s.stop_id, s.stop_name, s.stop_lat, s.stop_lon"
    if method == "rtree":
        return conn.execute(f"SELECT {cols} FROM stops_rtree r JOIN stops s ON s.rowid = r.id WHERE r.max_lat >= ? AND r.min_lat <= ? "
                            "AND r.max_lon >= ? AND r.min_lon <= ?", (lo_lat, hi_lat, lo_lon, hi_lon)).fetchall()
    if method == "grid":
        c0, c1 = math.floor(lo_lat / GRID_CELL_DEG), math.floor(hi_lat / GRID_CELL_DEG)
        d0, d1 = math.floor(lo_lon / GRID_CELL_DEG), math.floor(hi_lon / GRID_CELL_DEG)
        return conn.execute(f"SELECT {cols} FROM stops_grid g JOIN stops s ON s.stop_id = g.stop_id WHERE g.cell_lat BETWEEN ? AND ? "
                            "AND g.cell_lon BETWEEN ? AND ? AND s.stop_lat BETWEEN ? AND ? AND s.stop_lon BETWEEN ? AND ?",
                            (c0, c1, d0, d1, lo_lat, hi_lat, lo_lon, hi_lon)).fetchall()
    return conn.execute(f"SELECT {cols} FROM stops s WHERE s.stop_lat BETWEEN ? AND ? AND s.stop_lon BETWEEN ? AND ?",
                        (lo_lat, hi_lat, lo_lon, hi_lon)).fetchall()


def route_summaries(conn: sqlite3.Connection, stop_ids: list[str]) -> dict[str, tuple[int, list[str], int]]:
    """stop_id -> (routes_count, route_names capped, scheduled call count). Real data only."""
    out: dict[str, tuple[int, list[str], int]] = {}
    if not stop_ids:
        return out
    marks = ",".join("?" for _ in stop_ids)
    derived = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'stop_routes'").fetchone() is not None
    if derived:
        rows = conn.execute(f"SELECT sr.stop_id, r.route_short_name, r.route_long_name, r.route_id, sr.call_count FROM stop_routes sr "
                            f"JOIN routes r ON r.route_id = sr.route_id WHERE sr.stop_id IN ({marks})", stop_ids).fetchall()
    else:
        rows = conn.execute(f"SELECT st.stop_id, r.route_short_name, r.route_long_name, r.route_id, COUNT(*) FROM stop_times st "
                            f"JOIN trips t ON t.trip_id = st.trip_id JOIN routes r ON r.route_id = t.route_id "
                            f"WHERE st.stop_id IN ({marks}) GROUP BY st.stop_id, r.route_id", stop_ids).fetchall()
    per: dict[str, list[tuple[int, str, str]]] = {}
    for sid, short, long_, rid, calls in rows:
        per.setdefault(sid, []).append((calls, short or long_ or rid, rid))
    for sid, items in per.items():
        items.sort(key=lambda x: (-x[0], x[1], x[2]))
        names: list[str] = []
        for _, n, _ in items:
            if n not in names:
                names.append(n)
        out[sid] = (len(items), names[:ROUTE_NAMES_CAP], sum(i[0] for i in items))
    return out


def nearby_stops(conn: sqlite3.Connection, lat: float, lon: float, radius_m: int, limit: int) -> dict[str, Any]:
    method = spatial_method(conn)
    hits = []
    for row in _candidates(conn, lat, lon, radius_m, method):
        d = haversine_m(lat, lon, row["stop_lat"], row["stop_lon"])
        if d <= radius_m:
            hits.append((d, row["stop_id"], row))
    hits.sort(key=lambda h: (h[0], h[1]))
    total = len(hits)
    top = hits[:limit]
    summ = route_summaries(conn, [h[1] for h in top])
    cluster_of: dict[str, str] = {}
    if top and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'cluster_members'").fetchone():
        marks = ",".join("?" for _ in top)
        cluster_of = dict(conn.execute(f"SELECT stop_id, cluster_id FROM cluster_members WHERE stop_id IN ({marks})", [h[1] for h in top]).fetchall())
    items = []
    for d, sid, row in top:
        b = bearing_deg(lat, lon, row["stop_lat"], row["stop_lon"])
        count, names, calls = summ.get(sid, (0, [], 0))
        items.append({"stop_id": sid, "stop_name": row["stop_name"], "stop_lat": row["stop_lat"], "stop_lon": row["stop_lon"],
                      "distance_m": int(round(d)), "bearing_deg": int(round(b)) % 360, "compass": compass(b),
                      "routes_count": count, "route_names": names, "cluster_id": cluster_of.get(sid)})
    return {"radius_m": radius_m, "limit": limit, "total_in_radius": total, "returned": len(items), "index": method, "items": items,
            "data_basis": "gtfs_stops", "notice": "Distances are straight-line from the given point to each stop; they are not walking distances."}
