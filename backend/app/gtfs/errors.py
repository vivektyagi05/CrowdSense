"""Exception hierarchy for GTFS import failures.

Every failure carries the phase it happened in and a list of structured error
records, so the CLI, the status file and the logs all report the same facts.
"""

from __future__ import annotations

from typing import Any


class GtfsImportError(Exception):
    """Base class. ``errors`` holds JSON-serialisable detail records."""

    def __init__(self, message: str, *, phase: str = "unknown", errors: list[dict[str, Any]] | None = None,
                 total_errors: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.phase = phase
        self.errors: list[dict[str, Any]] = errors or []
        # ``errors`` is a bounded sample; ``total_errors`` is the true number of problems.
        self.total_errors = total_errors if total_errors is not None else len(self.errors)
        self.report: Any = None  # ImportReport, attached by the importer


class GtfsArchiveError(GtfsImportError):
    """The ZIP is unreadable, incomplete, ambiguous or has invalid headers."""


class GtfsDataError(GtfsImportError):
    """Row-level or referential validation failed."""


class PromotionError(GtfsImportError):
    """The validated staging database could not be promoted safely."""


class ImportLockedError(GtfsImportError):
    """Another import is already running against the same database."""
