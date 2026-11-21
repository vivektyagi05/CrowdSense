"""Synthetic GTFS fixtures. Test-only data; never used by application code."""

from __future__ import annotations

import zipfile
from pathlib import Path

FILES: dict[str, str] = {
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,Alpha Stop,28.60,77.20\nB,Beta Stop,28.61,77.21\n"
                 "C,Gamma 50%_Stop,28.62,77.22\nD,Delta Stop,28.63,77.23\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR1,101,Alpha to Gamma,3\nR2,NIGHT,,3\n",
    "trips.txt": "route_id,service_id,trip_id\nR1,S1,T1\nR1,S1,T2\nR2,S1,T3\nR1,S2,T4\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,A,1\nT1,08:10:00,08:10:00,B,2\nT1,08:20:00,08:20:00,C,3\n"
        "T2,09:00:00,09:00:00,A,1\nT2,09:10:00,09:10:00,B,2\nT2,09:20:00,09:20:00,C,3\n"
        "T3,23:50:00,23:50:00,A,1\nT3,24:10:00,24:10:00,B,2\n"
        "T4,10:00:00,10:00:00,A,1\nT4,10:30:00,10:30:00,D,2\n"
    ),
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "S1,1,1,1,1,1,1,1,20250101,20401231\n",
    "calendar_dates.txt": "service_id,date,exception_type\nS2,20261109,1\nS1,20261110,2\n",
}


def build_zip(path: Path, *, nested: bool = False, overrides: dict[str, str | None] | None = None,
              extra: dict[str, str] | None = None, base: dict[str, str] | None = None) -> Path:
    """Write a GTFS ZIP. ``overrides`` replaces file text; ``None`` removes the file."""
    files = dict(base if base is not None else FILES)
    for name, content in (overrides or {}).items():
        if content is None:
            files.pop(name, None)
        else:
            files[name] = content
    files.update(extra or {})
    prefix = "feed_v1/" if nested else ""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(prefix + name, content)
    return path
