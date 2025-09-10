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

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = None  # docker-compose passes envs; local can export or use a .env loader


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
