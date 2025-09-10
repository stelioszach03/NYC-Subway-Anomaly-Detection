from typing import Generator
from datetime import timezone
from zoneinfo import ZoneInfo

from .core.config import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


def get_db_session() -> Generator[None, None, None]:
    # Placeholder for real DB session dependency
    yield


NY = ZoneInfo("America/New_York")


def serialize_ts(dt):
    """Serialize a tz-aware datetime to canonical fields.

    Returns dict: ts_utc, ts_epoch_ms, ts_ny
    """
    if dt is None:
        return {"ts_utc": None, "ts_epoch_ms": None, "ts_ny": None}
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return {
        "ts_utc": dt_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ts_epoch_ms": int(dt_utc.timestamp() * 1000),
        "ts_ny": dt_utc.astimezone(NY).isoformat(timespec="seconds"),
    }


# New generic packer for observed/event semantics
def ts_pack(dt):
    if dt is None:
        return {"utc": None, "epoch_ms": None, "ny": None}
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return {
        "utc": dt_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "epoch_ms": int(dt_utc.timestamp() * 1000),
        "ny": dt.astimezone(NY).isoformat(timespec="seconds"),
    }


def pack_with_prefix(prefix: str, dt):
    p = ts_pack(dt)
    return {
        f"{prefix}_ts_utc": p["utc"],
        f"{prefix}_ts_epoch_ms": p["epoch_ms"],
        f"{prefix}_ts_ny": p["ny"],
    }
