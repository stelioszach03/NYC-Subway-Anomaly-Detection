from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import Score
from ..deps import ts_pack
from ..storage.session import get_engine


router = APIRouter(prefix="/summary", tags=["summary"])  # /api/summary


class SummaryOut(BaseModel):
    window: str
    stations_total: int
    trains_active: int
    anomalies_count: int
    anomalies_high: int
    anomaly_rate_perc: float
    last_updated_utc: str | None = None
    last_updated_epoch_ms: int | None = None
    last_updated_ny: str | None = None


def _parse_window(window: str) -> int:
    # very small parser: supports Xm / Xh
    s = window.strip().lower()
    if s.endswith("m"):
        n = int(s[:-1])
        return n * 60
    if s.endswith("h"):
        n = int(s[:-1])
        return n * 3600
    return 15 * 60


@router.get("", response_model=SummaryOut)
async def get_summary(window: str = Query(default="15m")) -> dict:
    now = datetime.now(timezone.utc)
    seconds = _parse_window(window)
    since = now - timedelta(seconds=seconds)

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionLocal() as session:
        total_rows = (
            session.execute(select(func.count(Score.id)).where(Score.observed_ts >= since)).scalar() or 0
        )
        # important: apply .where() to the Select, not inside func.count(...)
        stations_total = (
            session.execute(
                select(func.count(func.distinct(Score.stop_id))).where(Score.observed_ts >= since)
            ).scalar()
            or 0
        )
        # trains_active approximation: distinct (route_id, stop_id) with observed headway signal
        trains_active = (
            session.execute(
                select(func.count(func.distinct(func.concat(Score.route_id, ":", Score.stop_id))))
                .where(Score.observed_ts >= since)
                .where(Score.headway_sec.is_not(None))
                .where(Score.headway_sec > 0)
            ).scalar()
            or 0
        )
        anomalies_count = (
            session.execute(
                select(func.count(Score.id)).where(Score.observed_ts >= since).where(Score.anomaly_score >= 0.6)
            ).scalar()
            or 0
        )
        anomalies_high = (
            session.execute(
                select(func.count(Score.id)).where(Score.observed_ts >= since).where(Score.anomaly_score >= 0.85)
            ).scalar()
            or 0
        )

    anomaly_rate = float(anomalies_count) / float(total_rows) * 100.0 if total_rows else 0.0

    # Compute last_updated from max(observed_ts)
    with SessionLocal() as session:
        max_obs = session.execute(select(func.max(Score.observed_ts))).scalar()
    p = ts_pack(max_obs or now)
    return {
        "window": window,
        "stations_total": int(stations_total),
        "trains_active": int(trains_active),
        "anomalies_count": int(anomalies_count),
        "anomalies_high": int(anomalies_high),
        "anomaly_rate_perc": round(anomaly_rate, 2),
        # Canonical timestamp fields based on observed_ts
        "last_updated_utc": p["utc"],
        "last_updated_epoch_ms": p["epoch_ms"],
        "last_updated_ny": p["ny"],
    }
