import os
from typing import Literal, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App metadata
    APP_NAME: str = "mta-subway-anomaly-scan"
    APP_ENV: Literal["dev", "prod"] = "dev"
    APP_VERSION: str = "0.1.0"

    # Database
    DB_URL: str = "postgresql://postgres:postgres@db:5432/mta"

    # External tokens (optional for API/runtime; required for UI build)
    MAPBOX_TOKEN: str | None = None

    # Static GTFS paths (host defaults)
    # Prefer container mount path; for local host dev set via envs
    MTA_GTFS_STATIC_PATH: str = "/data/gtfs/mta_gtfs_static.zip"
    GTFS_STATIC_DIR: str = "/data/gtfs"
    MODEL_TELEMETRY_PATH: str = "/data/gtfs/models/telemetry.json"

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = None  # docker-compose passes envs; local can export or use a .env loader


_settings: Optional[Settings] = None
_settings_sig: tuple | None = None


def _env_signature() -> tuple:
    keys = (
        "APP_NAME",
        "APP_ENV",
        "APP_VERSION",
        "DB_URL",
        "MAPBOX_TOKEN",
        "MTA_GTFS_STATIC_PATH",
        "GTFS_STATIC_DIR",
        "MODEL_TELEMETRY_PATH",
        "LOG_LEVEL",
    )
    return tuple((k, os.environ.get(k)) for k in keys)


def get_settings() -> Settings:
    global _settings, _settings_sig
    sig = _env_signature()
    if _settings is None or _settings_sig != sig:
        _settings = Settings()  # type: ignore[call-arg]
        _settings_sig = sig
    return _settings
