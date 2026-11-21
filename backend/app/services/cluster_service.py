"""Place clusters: one place, several physical stops. Distinguishing information comes only from real data."""
from __future__ import annotations

import sqlite3

from app.derived.build import CLUSTER_THRESHOLD_M
from app.errors import AppError
from app.geo.planar import haversine_m
from app.services.nearby_service import bearing_deg, compass, route_summaries

NOTICE = ("Stops of one place share a name and lie within the cluster distance of each other. They are different physical "
          "stops (often opposite sides of a road): choose the specific stop you board at. The feed publishes no headsigns, "
          "so no 'towards' labels are shown unless headsigns exist.")


def derived_ready(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'clusters'").fetchone() is not None


def meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM derived_meta").fetchall())


def get_cluster(conn: sqlite3.Connection, cluster_id: str) -> dict:
    if not derived_ready(conn):
        raise AppError(503, "derived_data_missing", "Place clusters have not been built. Run: python -m scripts.build_derived")
    c = conn.execute("SELECT * FROM clusters WHERE cluster_id = ?", (cluster_id,)).fetchone()
    if c is None:
        raise AppError(404, "cluster_not_found", f"Unknown cluster_id: {cluster_id!r}.")
    m = meta(conn)
    rows = conn.execute("SELECT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon FROM cluster_members cm JOIN stops s ON s.stop_id = cm.stop_id "
                        "WHERE cm.cluster_id = ? ORDER BY s.stop_id", (cluster_id,)).fetchall()
    summ = route_summaries(conn, [r["stop_id"] for r in rows])
    has_headsigns = m.get("headsigns_available") == "true"
    members = []
    for r in rows:
        d = haversine_m(c["centroid_lat"], c["centroid_lon"], r["stop_lat"], r["stop_lon"])
        single = len(rows) == 1
        b = None if single else bearing_deg(c["centroid_lat"], c["centroid_lon"], r["stop_lat"], r["stop_lon"])
        count, names, calls = summ.get(r["stop_id"], (0, [], 0))
        heads: list[str] = []
        if has_headsigns:
            heads = [h[0] for h in conn.execute(
                "SELECT DISTINCT h FROM (SELECT t.trip_headsign AS h FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id WHERE st.stop_id = ? "
                "UNION SELECT stop_headsign FROM stop_times WHERE stop_id = ?) WHERE h IS NOT NULL AND trim(h) <> '' ORDER BY h LIMIT 5",
                (r["stop_id"], r["stop_id"])).fetchall()]
        members.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "stop_lat": r["stop_lat"], "stop_lon": r["stop_lon"],
                        "distance_from_centroid_m": int(round(d)), "bearing_from_centroid_deg": None if b is None else int(round(b)) % 360,
                        "compass": None if b is None else compass(b), "routes_count": count, "route_names": names,
                        "scheduled_calls": calls, "headsigns": heads})
    return {"cluster_id": c["cluster_id"], "display_name": c["display_name"], "centroid_lat": c["centroid_lat"], "centroid_lon": c["centroid_lon"],
            "stop_count": c["stop_count"], "members": members, "rule": m.get("cluster_rule", ""),
            "threshold_m": float(m.get("cluster_threshold_m", CLUSTER_THRESHOLD_M)), "headsigns_available": has_headsigns, "notice": NOTICE}
