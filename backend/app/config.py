"""Centralised, environment-driven configuration.

All runtime settings are read from environment variables (optionally seeded from
``backend/.env``) and validated *once*, at start-up. Real environment variables
always win over values in ``.env``.

Variables
---------
APP_ENV               development | test | production        (default: development)
BACKEND_HOST          bind address used by ``python -m app``   (default: 127.0.0.1)
BACKEND_PORT          bind port used by ``python -m app``      (default: 8000)
DATABASE_PATH         SQLite database file                     (default: backend/data/crowdsense.sqlite3)
GTFS_ZIP              GTFS ZIP consumed by the importer        (default: backend/data/delhi_buses_static_gtfs_v1.zip)
CORS_ALLOWED_ORIGINS  comma-separated browser origins          (default: the Vite dev server origins)
LOG_LEVEL             DEBUG | INFO | WARNING | ERROR | CRITICAL (default: INFO)

Relative paths are resolved against the ``backend/`` directory, never against the
current working directory, so the API and the importer always agree on the
location of the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parents[1]  # .../backend
DATA_DIR = BASE_DIR / "data"
DEFAULT_DATABASE_PATH = DATA_DIR / "crowdsense.sqlite3"
DEFAULT_GTFS_ZIP = DATA_DIR / "delhi_buses_static_gtfs_v1.zip"
DEFAULT_DOTENV_PATH = BASE_DIR / ".env"

VALID_ENVIRONMENTS = ("development", "test", "production")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


class ConfigError(ValueError):
    """Raised when the environment describes an invalid configuration."""


@dataclass(frozen=True)
class Settings:
    app_env: str
    host: str
    port: int
    database_path: Path
    gtfs_zip: Path
    cors_allowed_origins: tuple[str, ...]
    log_level: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        dotenv_path: Path | None = None,
        base_dir: Path = BASE_DIR,
    ) -> "Settings":
        """Build validated settings.

        ``env`` defaults to ``os.environ``. A ``.env`` file is only consulted when
        ``env`` is not supplied explicitly (so tests are hermetic) or when
        ``dotenv_path`` is passed.
        """
        if env is None:
            merged = dict(read_dotenv(dotenv_path or DEFAULT_DOTENV_PATH))
            merged.update(os.environ)  # real environment overrides .env
        else:
            merged = dict(read_dotenv(dotenv_path)) if dotenv_path else {}
            merged.update(env)

        errors: list[str] = []

        app_env = merged.get("APP_ENV", "development").strip().lower()
        if app_env not in VALID_ENVIRONMENTS:
            errors.append(f"APP_ENV must be one of {', '.join(VALID_ENVIRONMENTS)} (got {app_env!r})")

        host = merged.get("BACKEND_HOST", "127.0.0.1").strip()
        if not host:
            errors.append("BACKEND_HOST must not be empty")

        port = 8000
        raw_port = merged.get("BACKEND_PORT", "8000").strip()
        try:
            port = int(raw_port)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            errors.append(f"BACKEND_PORT must be an integer between 1 and 65535 (got {raw_port!r})")

        log_level = merged.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            errors.append(f"LOG_LEVEL must be one of {', '.join(VALID_LOG_LEVELS)} (got {log_level!r})")

        database_path = _resolve_path(merged.get("DATABASE_PATH"), DEFAULT_DATABASE_PATH, base_dir)
        if database_path.is_dir():
            errors.append(f"DATABASE_PATH points at a directory, not a file: {database_path}")

        gtfs_zip = _resolve_path(merged.get("GTFS_ZIP"), DEFAULT_GTFS_ZIP, base_dir)

        raw_origins = merged.get("CORS_ALLOWED_ORIGINS")
        origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
        if raw_origins is not None and raw_origins.strip():
            origins, origin_errors = _parse_origins(raw_origins)
            errors.extend(origin_errors)
        elif app_env == "production":
            errors.append("CORS_ALLOWED_ORIGINS must be set explicitly when APP_ENV=production")
        if app_env == "production" and "*" in origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain '*' when APP_ENV=production")

        if errors:
            raise ConfigError("Invalid configuration: " + "; ".join(errors))

        return cls(
            app_env=app_env,
            host=host,
            port=port,
            database_path=database_path,
            gtfs_zip=gtfs_zip,
            cors_allowed_origins=origins,
            log_level=log_level,
        )


def _resolve_path(raw: str | None, default: Path, base_dir: Path) -> Path:
    value = Path(raw.strip()).expanduser() if raw and raw.strip() else default
    if not value.is_absolute():
        value = base_dir / value
    return value.resolve()


def _parse_origins(raw: str) -> tuple[tuple[str, ...], list[str]]:
    origins: list[str] = []
    errors: list[str] = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            origins.append(origin)
            continue
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
            errors.append(f"CORS origin {item.strip()!r} must look like http(s)://host[:port] with no path")
            continue
        origins.append(origin)
    if not origins and not errors:
        errors.append("CORS_ALLOWED_ORIGINS contains no origins")
    return tuple(dict.fromkeys(origins)), errors


def read_dotenv(path: Path | None) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` file. Missing file -> empty dict.

    Supports comments, blank lines, an optional ``export`` prefix and single or
    double quoted values. It performs no variable expansion.
    """
    if path is None or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path.name}:{line_number}: expected KEY=VALUE")
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
