from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..core.config import get_settings


router = APIRouter(prefix="/replay", tags=["replay"])


def _artifact_dir() -> Path:
    return Path(get_settings().REPLAY_ARTIFACT_DIR)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Replay artifact not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Replay artifact is invalid JSON: {exc}") from exc


@router.get("/summary")
async def replay_summary() -> dict[str, Any]:
    return _load_json(_artifact_dir() / "summary.json")


@router.get("/timeline")
async def replay_timeline(
    incident_id: str | None = Query(default=None),
    limit: int = Query(default=400, ge=20, le=5000),
) -> dict[str, Any]:
    payload = _load_json(_artifact_dir() / "timeline.json")
    points = payload.get("points", []) if isinstance(payload, dict) else []
    if incident_id:
        points = [point for point in points if point.get("incident_id") == incident_id]
    return {"points": points[:limit]}


@router.get("/incidents")
async def replay_incidents() -> dict[str, Any]:
    return _load_json(_artifact_dir() / "incidents.json")


@router.get("/incidents/{incident_id}")
async def replay_incident_detail(incident_id: str) -> dict[str, Any]:
    incidents_payload = _load_json(_artifact_dir() / "incidents.json")
    incidents = incidents_payload.get("incidents", []) if isinstance(incidents_payload, dict) else []
    for incident in incidents:
        if incident.get("incident_id") == incident_id:
            detail_path = incident.get("detail_path")
            if not detail_path:
                break
            return _load_json(_artifact_dir() / str(detail_path))
    raise HTTPException(status_code=404, detail=f"Replay incident not found: {incident_id}")
