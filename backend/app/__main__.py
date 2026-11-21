"""``python -m app`` - run the API using BACKEND_HOST / BACKEND_PORT / LOG_LEVEL."""

import uvicorn

from app.config import Settings

if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level=settings.log_level.lower())  # access lines are redacted by app.logging_config (lat/lon values)
