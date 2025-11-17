from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from ..deps import ts_pack
from ..models import Score
from ..storage.session import get_engine
from .stops import _load_stops


router = APIRouter(tags=["health"])


def _read_model_telemetry(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {"status": "unavailable"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"status": "unavailable"}
        out = {"status": "available"}
        for key in ("rows_seen", "rows_updated", "drift_events", "mae_ema", "last_run_utc"):
            if key in data:
                out[key] = data[key]
        return out
    except Exception as e:
        return {"status": "error", "error": repr(e)}


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"status": "ok", "version": s.APP_VERSION}


@router.get("/health/deep")
async def deep_health() -> dict:
    s = get_settings()
    now = datetime.now(timezone.utc)
    checks: dict = {}
    overall_status = "ok"

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        with SessionLocal() as session:
            session.execute(select(1)).scalar()
            total_scores = int(session.execute(select(func.count(Score.id))).scalar() or 0)
            recent_since = now.timestamp() - 900
            recent_scores = int(
                session.execute(
                    select(func.count(Score.id)).where(
                        Score.observed_ts >= datetime.fromtimestamp(recent_since, tz=timezone.utc)
                    )
                ).scalar()
                or 0
            )
            max_obs = session.execute(select(func.max(Score.observed_ts))).scalar()
        max_pack = ts_pack(max_obs) if max_obs else {"utc": None, "epoch_ms": None, "ny": None}
        age_sec = int(now.timestamp() - (max_obs.timestamp() if max_obs else now.timestamp()))
        checks["db"] = {
            "ok": True,
            "scores_total": total_scores,
            "scores_recent_15m": recent_scores,
            "last_observed_utc": max_pack["utc"],
            "last_observed_epoch_ms": max_pack["epoch_ms"],
            "last_observed_ny": max_pack["ny"],
            "last_observed_age_sec": age_sec if max_obs else None,
            "fresh": bool(max_obs is not None and age_sec <= 900),
        }
        if max_obs is None or age_sec > 900:
            overall_status = "degraded"
    except Exception as e:
        checks["db"] = {"ok": False, "error": repr(e)}
        overall_status = "degraded"

    try:
        stops_count = len(_load_stops())
        checks["gtfs"] = {"ok": stops_count > 0, "stops_count": int(stops_count)}
        if stops_count == 0:
            overall_status = "degraded"
    except Exception as e:
        checks["gtfs"] = {"ok": False, "error": repr(e)}
        overall_status = "degraded"

    checks["model"] = _read_model_telemetry(s.MODEL_TELEMETRY_PATH)
    if checks["model"].get("status") == "error":
        overall_status = "degraded"

    return {
        "status": overall_status,
        "version": s.APP_VERSION,
        "checks": checks,
        "timestamp_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


@router.get("/debug/stats")
async def debug_stats() -> dict:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as session:
        total = int(session.execute(select(func.count(Score.id))).scalar() or 0)
        headway_ready = int(
            session.execute(select(func.count(Score.id)).where(Score.headway_sec.is_not(None))).scalar() or 0
        )
        scored = int(
            session.execute(select(func.count(Score.id)).where(Score.predicted_headway_sec.is_not(None))).scalar()
            or 0
        )
    return {
        "scores_total": total,
        "headway_ready": headway_ready,
        "scored_rows": scored,
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }
