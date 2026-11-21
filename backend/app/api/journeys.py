"""Direct journey search endpoint."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db
from app.schemas import JourneySearchResponse
from app.services.journey_service import find_direct_journeys

router = APIRouter(tags=["journeys"])


@router.get(
    "/journeys",
    response_model=JourneySearchResponse,
    response_model_exclude_none=True,
    summary="Scheduled direct bus journeys between two stops",
)
def direct_journeys(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    origin_stop_id: Annotated[str, Query(min_length=1, max_length=255)],
    destination_stop_id: Annotated[str, Query(min_length=1, max_length=255)],
    departure: Annotated[str, Query(min_length=1, max_length=64, description="Local ISO datetime, e.g. 2026-11-09T08:00:00")],
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> JourneySearchResponse:
    return find_direct_journeys(conn, origin_stop_id, destination_stop_id, departure, limit)
