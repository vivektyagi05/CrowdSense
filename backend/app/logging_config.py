"""Application logging setup.

Only the ``app`` logger hierarchy is configured, so uvicorn's own loggers keep
their behaviour. Never log secrets, request bodies or passenger information.
"""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_HANDLER_FLAG = "_crowdsense_handler"


def configure_logging(level: str = "INFO") -> None:
    """Idempotently attach one stream handler to the ``app`` logger."""
    logger = logging.getLogger("app")
    logger.setLevel(level.upper())
    if not any(getattr(h, _HANDLER_FLAG, False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        setattr(handler, _HANDLER_FLAG, True)
        logger.addHandler(handler)
    logger.propagate = False
    install_privacy_filters()


# --- Privacy (Phase 4): coordinates must never reach a log --------------------------------------------------------
import re as _re

_COORD_PARAM = _re.compile(r"(?i)([?&](?:lat|lon|latitude|longitude|lng)=)[^&\s\"]*")


def redact_coordinates(text: str) -> str:
    """Replace the values of lat/lon query parameters with ``[redacted]``."""
    return _COORD_PARAM.sub(r"\1[redacted]", text)


class RedactCoordinatesFilter(logging.Filter):
    """Strips lat/lon query values from uvicorn access-log records (``uvicorn.access`` puts the path in ``args``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_coordinates(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact_coordinates(record.msg)
        return True


def install_privacy_filters() -> None:
    """Idempotently attach the filter to uvicorn's access/error loggers and to our own."""
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn", "app"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactCoordinatesFilter) for f in logger.filters):
            logger.addFilter(RedactCoordinatesFilter())
        for h in logger.handlers:      # logger-level filters do not apply to records from child loggers; handlers do
            if not any(isinstance(f, RedactCoordinatesFilter) for f in h.filters):
                h.addFilter(RedactCoordinatesFilter())
