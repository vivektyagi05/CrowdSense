"""Centralised SQLite connection management.

Every connection in the application is created here so that pragmas, timeouts
and lifecycle rules are applied consistently.

Design notes
------------
* Connections run in autocommit mode (``isolation_level=None``); transactions are
  explicit via :func:`transaction`. This avoids the implicit-transaction surprises
  of the default ``sqlite3`` behaviour.
* Opening uses ``mode=rw`` (never ``rwc``): a missing database is an error, it is
  *not* silently created as an empty file.
* The API opens connections ``read_only=True``. That sets ``PRAGMA query_only``
  rather than ``mode=ro`` because a WAL-mode database needs write access to its
  ``-shm`` index even for readers.
* ``journal_mode=WAL`` is a property stored in the database file. It is set by
  the importer when it builds a database, and re-asserted here only for
  read-write connections.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_BUSY_TIMEOUT_MS = 5000


class DatabaseUnavailableError(Exception):
    """The database file is missing or cannot be opened as a SQLite database."""


def sqlite_uri(path: Path, mode: str = "rw") -> str:
    """Build a ``file:`` URI that is safe for spaces/backslashes (Windows paths)."""
    return f"{path.resolve().as_uri()}?mode={mode}"


def connect(
    path: Path,
    *,
    read_only: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open a configured connection to an *existing* database.

    The caller owns the connection and must close it; prefer
    :func:`open_connection` which does that automatically.
    """
    if not path.is_file():
        raise DatabaseUnavailableError(f"database file not found: {path}")
    try:
        conn = sqlite3.connect(
            sqlite_uri(path, "rw"),
            uri=True,
            timeout=busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=check_same_thread,
        )
    except sqlite3.Error as exc:  # e.g. permission problems
        raise DatabaseUnavailableError(f"cannot open database {path}: {exc}") from exc

    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        if read_only:
            conn.execute("PRAGMA query_only = ON")
        else:
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")  # fails fast on non-SQLite files
    except sqlite3.Error as exc:
        conn.close()
        raise DatabaseUnavailableError(f"{path} is not a usable SQLite database: {exc}") from exc
    return conn


@contextmanager
def open_connection(path: Path, **kwargs: object) -> Iterator[sqlite3.Connection]:
    """Context manager that always closes the connection."""
    conn = connect(path, **kwargs)  # type: ignore[arg-type]
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Run a block atomically: COMMIT on success, ROLLBACK on any exception."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
