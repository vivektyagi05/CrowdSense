"""Service calendar, feed summary and validation report."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db_v2, get_settings
from app.config import Settings
from app.gtfs.calendar import evaluate_services
from app.schemas import ActiveServicesResponse, GtfsSummary, ServiceOut, ValidationReport
from app.services.summary_service import get_summary, get_validation_report
from app.services.time_service import feed_timezone_name, feed_today

router = APIRouter()
Db = Annotated[sqlite3.Connection, Depends(get_db_v2)]


@router.get("/services/active", response_model=ActiveServicesResponse, tags=["services"],
            summary="Service ids running on a date (calendar + calendar_dates)")
def active_services(
    conn: Db,
    date_: Annotated[date | None, Query(alias="date", description="YYYY-MM-DD (default: today in the feed's timezone)")] = None,
    include_inactive: Annotated[bool, Query(description="Also list services that do not run, with the reason")] = False,
) -> ActiveServicesResponse:
    source = "request" if date_ else "today_in_feed_timezone"
    day = date_ or feed_today(conn)
    statuses = evaluate_services(conn, day)
    trips = {r[0]: r[1] for r in conn.execute("SELECT service_id, COUNT(*) FROM trips GROUP BY service_id")}
    active = [s for s in statuses if s.active]
    shown = statuses if include_inactive else active
    return ActiveServicesResponse(
        date=day.isoformat(), weekday=day.strftime("%A").lower(), date_source=source, timezone=feed_timezone_name(conn),
        active_service_ids=[s.service_id for s in active], active_count=len(active), inactive_count=len(statuses) - len(active),
        calendar_dates_present=conn.execute("SELECT EXISTS(SELECT 1 FROM calendar_dates)").fetchone()[0] == 1,
        services=[ServiceOut(service_id=s.service_id, active=s.active, reason=s.reason, trip_count=trips.get(s.service_id, 0)) for s in shown])


@router.get("/gtfs/summary", response_model=GtfsSummary, tags=["gtfs"], summary="What the imported feed contains (and what it does not)")
def gtfs_summary(conn: Db) -> GtfsSummary:
    return get_summary(conn)


@router.get("/gtfs/validation-report", response_model=ValidationReport, tags=["gtfs"],
            summary="Data-quality findings and integrity checks of the imported feed")
def gtfs_validation_report(conn: Db, settings: Annotated[Settings, Depends(get_settings)]) -> ValidationReport:
    return get_validation_report(conn, settings.database_path)
