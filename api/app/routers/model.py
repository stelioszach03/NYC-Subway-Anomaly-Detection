from __future__ import annotations

import json
import os

from fastapi import APIRouter

from ..core.config import get_settings


router = APIRouter(prefix="/model", tags=["model"])


def _load_json(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {"status": "unavailable"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"status": "unavailable"}
        payload = {"status": "available"}
        payload.update(data)
        payload["status"] = "available"
        return payload
    except Exception as e:
        return {"status": "error", "error": repr(e)}


@router.get("/telemetry")
async def model_telemetry() -> dict:
    settings = get_settings()
    payload = _load_json(settings.MODEL_TELEMETRY_PATH)

    if payload.get("status") == "available":
        filtered = {"status": "available"}
        for key in (
            "rows_seen",
            "rows_updated",
            "drift_events",
            "mae_ema",
            "residual_q90",
            "residual_q99",
            "last_batch_processed",
            "unscored_backlog",
            "last_run_utc",
        ):
            if key in payload:
                filtered[key] = payload[key]
        return filtered

    return payload


@router.get("/telemetry/dl-shadow")
async def dl_shadow_telemetry() -> dict:
    settings = get_settings()
    return _load_json(settings.MODEL_DL_TELEMETRY_PATH)
