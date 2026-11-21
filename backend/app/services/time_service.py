"""Date helpers that depend on the feed's own timezone."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from app.errors import AppError


def feed_timezone_name(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT agency_timezone FROM agency ORDER BY agency_id LIMIT 1").fetchone()
    return row[0] if row else None


def feed_today(conn: sqlite3.Connection) -> date:
    """Today's date in the agency timezone. Requires the timezone database (``tzdata`` on Windows)."""
    name = feed_timezone_name(conn)
    if name is None:
        raise AppError(400, "date_required", "The feed declares no timezone, so 'today' is unknown. Pass date=YYYY-MM-DD.")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(name)).date()
    except Exception:  # ZoneInfoNotFoundError / missing tz database
        raise AppError(400, "date_required",
                       f"Timezone {name!r} is unavailable on this server (install the 'tzdata' package). "
                       "Pass date=YYYY-MM-DD explicitly.") from None
