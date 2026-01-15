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
    scored_rows: int
    last_updated_utc: str | None = None
    last_updated_epoch_ms: int | None = None
    last_updated_ny: str | None = None


def _parse_window(window: str) -> int:
    s = window.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    return 15 * 60


@router.get("", response_model=SummaryOut)
async def get_summary(window: str = Query(default="15m")) -> dict:
    now = datetime.now(timezone.utc)
    seconds = _parse_window(window)

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionLocal() as session:
        # Anchor the window on the most recent row that has a prediction,
        # not wall-clock NOW. The trainer typically lags the collector by
        # a few minutes, so anchoring on NOW() makes the summary show
        # zeros even though data is flowing — aligning with the prediction
        # front mirrors what the live UI actually has available.
        max_pred_ts = session.execute(
            select(func.max(Score.observed_ts)).where(
                Score.predicted_headway_sec.is_not(None)
            )
        ).scalar()

        # Also keep an "overall" latest for the last_updated timestamp.
        max_obs = session.execute(select(func.max(Score.observed_ts))).scalar()

        anchor = max_pred_ts or max_obs or now
        since = anchor - timedelta(seconds=seconds)

        scored_rows = int(
            session.execute(
                select(func.count(Score.id))
                .where(Score.observed_ts >= since)
                .where(Score.predicted_headway_sec.is_not(None))
            ).scalar()
            or 0
        )

        stations_total = int(
            session.execute(
                select(func.count(func.distinct(Score.stop_id)))
                .where(Score.observed_ts >= since)
                .where(Score.predicted_headway_sec.is_not(None))
            ).scalar()
            or 0
        )

        trains_active = int(
            session.execute(
                select(func.count(func.distinct(func.concat(Score.route_id, ":", Score.stop_id))))
                .where(Score.observed_ts >= since)
                .where(Score.headway_sec.is_not(None))
                .where(Score.predicted_headway_sec.is_not(None))
                .where(Score.headway_sec > 0)
            ).scalar()
            or 0
        )

        anomalies_count = int(
            session.execute(
                select(func.count(Score.id))
                .where(Score.observed_ts >= since)
                .where(Score.predicted_headway_sec.is_not(None))
                .where(Score.anomaly_score >= 0.6)
            ).scalar()
            or 0
        )

        anomalies_high = int(
            session.execute(
                select(func.count(Score.id))
                .where(Score.observed_ts >= since)
                .where(Score.predicted_headway_sec.is_not(None))
                .where(Score.anomaly_score >= 0.85)
            ).scalar()
            or 0
        )

    anomaly_rate = float(anomalies_count) / float(scored_rows) * 100.0 if scored_rows else 0.0
    # last_updated reflects whichever is newer; observed front is more useful
    # for live-ness indicator than the prediction front.
    p = ts_pack(max_obs or now)

    return {
        "window": window,
        "stations_total": stations_total,
        "trains_active": trains_active,
        "anomalies_count": anomalies_count,
        "anomalies_high": anomalies_high,
        "anomaly_rate_perc": round(anomaly_rate, 2),
        "scored_rows": scored_rows,
        "last_updated_utc": p["utc"],
        "last_updated_epoch_ms": p["epoch_ms"],
        "last_updated_ny": p["ny"],
    }
