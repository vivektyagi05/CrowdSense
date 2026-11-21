"""Health endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import get_settings
from app.config import Settings
from app.schemas import HealthResponse, LivenessResponse
from app.services.health_service import build_health

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=LivenessResponse, summary="Liveness: the process is running")
def liveness() -> LivenessResponse:
    """Always 200 while the process can serve requests. Says nothing about data readiness."""
    return LivenessResponse(version=__version__)


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database or GTFS data not ready"}},
    summary="Readiness: application, database, GTFS data and crowd engine",
)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    """200 only when the database is reachable and GTFS data is loaded; otherwise 503."""
    body, status_code = build_health(settings)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
