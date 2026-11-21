"""Build derived data (spatial index, stop->routes, place clusters). Idempotent and deterministic.

    python -m scripts.build_derived                 # uses DATABASE_PATH from backend/.env
    python -m scripts.build_derived --db other.sqlite3 --force-grid
Run it again after every GTFS import (the importer replaces the database file).
"""
from __future__ import annotations

import argparse
import json
import time

from app.config import Settings
from app.derived.build import build_derived


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="database file (default: DATABASE_PATH)")
    ap.add_argument("--force-grid", action="store_true", help="use the indexed grid instead of the R-tree (fallback path)")
    args = ap.parse_args()
    path = args.db or Settings.from_env().database_path
    t = time.perf_counter()
    meta = build_derived(path, force_grid=args.force_grid)
    print(json.dumps(meta, indent=2)); print(f"built in {time.perf_counter() - t:.1f}s")


if __name__ == "__main__":
    main()
