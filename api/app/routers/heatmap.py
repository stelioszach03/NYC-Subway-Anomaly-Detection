from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import Score
from ..deps import pack_with_prefix
from ..storage.session import get_engine
from .stops import _load_stops


router = APIRouter(prefix="/heatmap", tags=["heatmap"]) 


def _parse_ts(ts_str: Optional[str]) -> datetime:
    if not ts_str or ts_str.lower() == "now":
        return datetime.now(timezone.utc)
    s = ts_str.strip()
    # Accept 'Z' suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _parse_window(window: str) -> int:
    s = window.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    return 60 * 60


@router.get("")
async def get_heatmap(
    ts: Optional[str] = Query(default="now"),
    window: str = Query(default="60m"),
    route_id: str = Query(default="All"),
) -> dict:
    target_ts = _parse_ts(ts)
    seconds = _parse_window(window)
    since = target_ts - timedelta(seconds=seconds)

    # Load stops for geometry lookup
    stops = _load_stops()
    stop_map: Dict[str, Dict] = {s["stop_id"]: s for s in stops}

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionLocal() as session:
        base = (
            select(
                Score.stop_id,
                func.avg(Score.anomaly_score).label("avg_score"),
                func.avg(Score.residual).label("avg_res"),
                func.avg(Score.headway_sec).label("avg_headway"),
                func.avg(Score.predicted_headway_sec).label("avg_pred_headway"),
                func.max(Score.observed_ts).label("max_observed_ts"),
                func.max(Score.event_ts).label("max_event_ts"),
                func.max(Score.route_id).label("route_id"),
            )
            .where(Score.observed_ts <= target_ts)
            .where(Score.observed_ts >= since)
        )
        if route_id and route_id.lower() != "all":
            base = base.where(Score.route_id == route_id)
        base = base.group_by(Score.stop_id)
        rows = session.execute(base).all()

    features: List[dict] = []
    for sid, avg_s, avg_r, avg_h, avg_pred_h, obs_ts_row, evt_ts_row, r_id in rows:
        st = stop_map.get(sid)
        if not st:
            continue
        geom = {"type": "Point", "coordinates": [st["lon"], st["lat"]]}
        props: Dict = {
            "stop_id": sid,
            "stop_name": st.get("stop_name"),
            "route_id": r_id,
            "anomaly_score": float(avg_s) if avg_s is not None else 0.0,
            "residual": float(avg_r) if avg_r is not None else 0.0,
            "headway_sec": float(avg_h) if avg_h is not None else None,
            "predicted_headway_sec": float(avg_pred_h) if avg_pred_h is not None else None,
        }
        # Add observed timestamp pack (primary)
        ts_observed = obs_ts_row or target_ts
        props.update(pack_with_prefix("observed", ts_observed))
        # Optionally include event pack if available in aggregation
        if evt_ts_row is not None:
            props.update(pack_with_prefix("event", evt_ts_row))

        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "timestamp": target_ts.isoformat(), "features": features}
