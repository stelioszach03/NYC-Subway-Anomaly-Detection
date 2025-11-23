from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from ..models import Score
from ..deps import pack_with_prefix
from ..storage.session import get_engine
from .stops import _load_stops


router = APIRouter(prefix="/anomalies", tags=["anomalies"])  # /api/anomalies


class AnomalyItem(BaseModel):
    route_id: str
    stop_id: str
    stop_name: str | None = None
    headway_sec: float | None = None
    predicted_headway_sec: float | None = None
    anomaly_score: float | None = None
    residual: float | None = None
    observed_ts_utc: str | None = None
    observed_ts_epoch_ms: int | None = None
    observed_ts_ny: str | None = None
    event_ts_utc: str | None = None
    event_ts_epoch_ms: int | None = None
    event_ts_ny: str | None = None


def _parse_window(window: str) -> int:
    s = window.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    return 15 * 60


@router.get("", response_model=List[AnomalyItem])
async def list_anomalies(
    window: str = Query(default="15m"),
    route_id: str = Query(default="All"),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=300, ge=20, le=1000),
) -> List[Dict]:
    seconds = _parse_window(window)
    since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionLocal() as session:
        stmt = (
            select(
                Score.observed_ts,
                Score.event_ts,
                Score.route_id,
                Score.stop_id,
                Score.headway_sec,
                Score.predicted_headway_sec,
                Score.anomaly_score,
                Score.residual,
            )
            .where(Score.observed_ts >= since)
            .where(Score.predicted_headway_sec.is_not(None))
        )
        if route_id and route_id.lower() != "all":
            stmt = stmt.where(Score.route_id == route_id)
        if min_score > 0:
            stmt = stmt.where(Score.anomaly_score >= min_score)
        stmt = stmt.order_by(desc(Score.anomaly_score), desc(Score.observed_ts)).limit(limit)
        rows = session.execute(stmt).all()

    stops = {s["stop_id"]: s for s in _load_stops()}
    out: List[Dict] = []
    for observed_ts, event_ts, r, sid, headway, predicted, score, res in rows:
        name = stops.get(sid, {}).get("stop_name")
        item: Dict = {
            "route_id": r,
            "stop_id": sid,
            "stop_name": name,
            "headway_sec": float(headway) if headway is not None else None,
            "predicted_headway_sec": float(predicted) if predicted is not None else None,
            "anomaly_score": float(score) if score is not None else None,
            "residual": float(res) if res is not None else None,
        }
        item.update(pack_with_prefix("observed", observed_ts))
        item.update(pack_with_prefix("event", event_ts))
        out.append(item)
    return out
