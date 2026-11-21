from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.gtfs.importer import import_gtfs
from app.main import create_app
from tests.gtfs_factory import build_zip

REAL_DB = BASE_DIR / "data" / "crowdsense.sqlite3"


@pytest.fixture(scope="session", autouse=True)
def _real_database_untouched():
    """Fail the run if any test modified the developer's real database file."""
    before = REAL_DB.stat() if REAL_DB.exists() else None
    yield
    after = REAL_DB.stat() if REAL_DB.exists() else None
    assert (before and before.st_size, before and before.st_mtime_ns) == (after and after.st_size, after and after.st_mtime_ns), \
        "a test modified the real database!"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(tmp_path / "db" / "test.sqlite3"),
                              "GTFS_ZIP": str(tmp_path / "feed.zip")})


@pytest.fixture
def feed_zip(tmp_path: Path) -> Path:
    return build_zip(tmp_path / "feed.zip")


@pytest.fixture
def imported(settings: Settings, feed_zip: Path) -> Settings:
    import_gtfs(feed_zip, settings.database_path, promote_retries=0)
    return settings


@pytest.fixture
def client(imported: Settings) -> TestClient:
    return TestClient(create_app(imported), raise_server_exceptions=False)


@pytest.fixture
def empty_client(settings: Settings) -> TestClient:
    """App pointed at a database that does not exist."""
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def full_zip(tmp_path: Path) -> Path:
    from tests.gtfs_full import FULL_FILES
    return build_zip(tmp_path / "full.zip", base=FULL_FILES)


@pytest.fixture
def full_settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"APP_ENV": "test", "DATABASE_PATH": str(tmp_path / "full" / "full.sqlite3"),
                              "GTFS_ZIP": str(tmp_path / "full.zip")})


@pytest.fixture
def full_client(full_settings: Settings, full_zip: Path) -> TestClient:
    """API over a database built from the complete synthetic feed (all supported files)."""
    import_gtfs(full_zip, full_settings.database_path, promote_retries=0)
    return TestClient(create_app(full_settings), raise_server_exceptions=False)
