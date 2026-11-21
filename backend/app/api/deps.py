"""FastAPI dependencies: settings and a request-scoped, always-closed DB connection."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, Request

from app.config import Settings
from app.db import connect
from app.errors import AppError

MIN_PHASE1_SCHEMA = 2


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """One read-only connection per request, closed when the response is done.

    FastAPI may run a sync dependency's setup, the endpoint and its teardown on
    different worker threads, hence ``check_same_thread=False``. The connection is
    never shared between requests, so this is safe.
    """
    conn = connect(get_settings(request).database_path, read_only=True, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def get_db_v2(conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Connection:
    """Like :func:`get_db`, but refuses databases built before schema version 2 (Phase 0 imports).

    Phase 0 databases still serve the Phase 0 endpoints; the Phase 1 endpoints need the new tables, and a clear
    503 beats an opaque "no such table" error.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < MIN_PHASE1_SCHEMA:
        raise AppError(503, "schema_outdated",
                       "The GTFS database was built by an older importer. Run: python -m scripts.import_gtfs")
    return conn
