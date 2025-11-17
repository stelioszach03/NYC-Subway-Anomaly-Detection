from __future__ import annotations

import json
import os

from fastapi import APIRouter

from ..core.config import get_settings


router = APIRouter(prefix="/model", tags=["model"])


@router.get("/telemetry")
async def model_telemetry() -> dict:
    settings = get_settings()
    path = settings.MODEL_TELEMETRY_PATH
    if not path or not os.path.exists(path):
        return {"status": "unavailable"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"status": "unavailable"}
        payload = {"status": "available"}
        for key in ("rows_seen", "rows_updated", "drift_events", "mae_ema", "last_run_utc"):
            if key in data:
                payload[key] = data[key]
        return payload
    except Exception as e:
        return {"status": "error", "error": repr(e)}
