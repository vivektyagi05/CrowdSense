"""Consistent, safe error responses.

Every error body is ``{"error": {"code", "message", "details"?}, "detail": message}``.
``detail`` duplicates the message so clients written against the original API
(which read FastAPI's ``detail`` string) keep working.

Unexpected exceptions are logged with a traceback server-side and answered with
a generic message: internals never reach API consumers.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import DatabaseUnavailableError
from app.errors import AppError

logger = logging.getLogger(__name__)

_HTTP_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 422: "validation_error"}


def _body(status_code: int, code: str, message: str, details: list[dict] | None = None) -> JSONResponse:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error, "detail": message})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _body(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _body(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "query"), "message": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        return _body(422, "validation_error", "Invalid request parameters.", jsonable_encoder(details))

    @app.exception_handler(DatabaseUnavailableError)
    async def _db_unavailable(request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        logger.error("Database unavailable for %s %s: %s", request.method, request.url.path, exc)
        return _body(503, "database_unavailable",
                     "The GTFS database is not available. Run the GTFS import, then retry.")

    @app.exception_handler(sqlite3.Error)
    async def _sqlite_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logger.exception("Database error for %s %s", request.method, request.url.path)
        return _body(503, "database_error", "The database could not complete the request.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error for %s %s", request.method, request.url.path)
        return _body(500, "internal_error", "Internal server error.")
