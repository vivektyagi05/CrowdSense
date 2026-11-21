from pathlib import Path

import pytest

from app.config import BASE_DIR, ConfigError, Settings, read_dotenv


def test_defaults_are_safe_for_local_development():
    s = Settings.from_env({})
    assert s.app_env == "development" and s.host == "127.0.0.1" and s.port == 8000
    assert s.database_path == (BASE_DIR / "data" / "crowdsense.sqlite3").resolve()
    assert s.cors_allowed_origins == ("http://localhost:5173", "http://127.0.0.1:5173")
    assert s.log_level == "INFO"


def test_env_overrides_and_relative_paths_resolve_against_backend_dir():
    s = Settings.from_env({"APP_ENV": "test", "BACKEND_PORT": "9001", "DATABASE_PATH": "data/x.sqlite3",
                           "LOG_LEVEL": "debug", "CORS_ALLOWED_ORIGINS": "http://a.test:3000/, https://b.test"})
    assert s.port == 9001 and s.log_level == "DEBUG"
    assert s.database_path == (BASE_DIR / "data" / "x.sqlite3").resolve()
    assert s.cors_allowed_origins == ("http://a.test:3000", "https://b.test")


@pytest.mark.parametrize("env", [
    {"APP_ENV": "staging"}, {"BACKEND_PORT": "abc"}, {"BACKEND_PORT": "70000"}, {"LOG_LEVEL": "LOUD"},
    {"CORS_ALLOWED_ORIGINS": "localhost:5173"}, {"CORS_ALLOWED_ORIGINS": "http://x.test/path"},
])
def test_invalid_values_fail_at_startup(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_all_problems_are_reported_together():
    with pytest.raises(ConfigError) as exc:
        Settings.from_env({"APP_ENV": "x", "BACKEND_PORT": "0"})
    assert "APP_ENV" in str(exc.value) and "BACKEND_PORT" in str(exc.value)


def test_production_requires_explicit_origins_and_rejects_wildcard():
    with pytest.raises(ConfigError, match="CORS_ALLOWED_ORIGINS"):
        Settings.from_env({"APP_ENV": "production"})
    with pytest.raises(ConfigError, match=r"\*"):
        Settings.from_env({"APP_ENV": "production", "CORS_ALLOWED_ORIGINS": "*"})
    assert Settings.from_env({"APP_ENV": "production", "CORS_ALLOWED_ORIGINS": "https://app.example"}).is_production


def test_database_path_directory_rejected(tmp_path):
    with pytest.raises(ConfigError, match="directory"):
        Settings.from_env({"DATABASE_PATH": str(tmp_path)})


def test_dotenv_is_parsed_and_real_env_wins(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text('# c\nexport LOG_LEVEL="warning"\nBACKEND_PORT=9100\n', encoding="utf-8")
    assert read_dotenv(f) == {"LOG_LEVEL": "warning", "BACKEND_PORT": "9100"}
    s = Settings.from_env({"BACKEND_PORT": "9200"}, dotenv_path=f)
    assert s.port == 9200 and s.log_level == "WARNING"
    assert read_dotenv(tmp_path / "missing") == {}


def test_malformed_dotenv_line_rejected(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("NOEQUALS\n")
    with pytest.raises(ConfigError):
        read_dotenv(f)
