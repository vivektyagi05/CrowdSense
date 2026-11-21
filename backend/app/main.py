"""Application factory and ASGI entry point (``uvicorn app.main:app``)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import gtfs, health, journeys, network, stops
from app.api.error_handlers import register_error_handlers
from app.config import Settings
from app.db import DatabaseUnavailableError, open_connection
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def _warm_search_index(settings: Settings) -> None:
    """Best-effort: build the smart-search index at startup so the first user request is not the slow one."""
    try:
        from app.db import connect
        from app.services import search_service
        if settings.database_path.exists():
            conn = connect(settings.database_path, read_only=True)
            try:
                search_service.get_index(conn)
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001 - warming must never stop the API from starting
        logger.warning("search index warm-up skipped: %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Invalid configuration raises ``ConfigError`` immediately."""
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("CrowdSense API %s starting (env=%s, database=%s)", __version__, settings.app_env,
                    settings.database_path.name)
        _log_database_state(settings)
        _warm_search_index(settings)
        yield
        logger.info("CrowdSense API shutting down")

    app = FastAPI(
        title="CrowdSense API",
        version=__version__,
        description="GTFS-powered bus planner. Only static GTFS is connected: no crowd/ETM data and no live vehicle tracking. Phase 1 adds a queryable GTFS data layer: agencies, stops, routes, trips, stop times, shapes, service calendars, feed summary and validation report.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=False,  # the API uses no cookies or HTTP auth
        allow_methods=["GET", "OPTIONS"],  # the API is read-only
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for router in (health.router, stops.router, network.router, gtfs.router, journeys.router):
        app.include_router(router, prefix=API_PREFIX)
    return app


def _log_database_state(settings: Settings) -> None:
    """Start-up diagnostics only: the app still starts, and /health reports readiness."""
    try:
        with open_connection(settings.database_path) as conn:
            conn.execute("SELECT 1").fetchone()
        logger.info("Database reachable")
    except DatabaseUnavailableError as exc:
        logger.warning("Database not ready at startup (%s). Run: python -m scripts.import_gtfs", exc)


app = create_app()
