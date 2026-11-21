"""Application-level errors that map onto structured HTTP responses."""

from __future__ import annotations


class AppError(Exception):
    """An expected, client-facing error.

    ``message`` is shown to API consumers, so it must never contain internal
    paths, SQL or stack traces.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
