from datetime import datetime, timezone
from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from ..models import Score
from ..storage.session import get_engine
from .stops import _load_stops


router = APIRouter(tags=["health"]) 


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"status": "ok", "version": s.APP_VERSION}


@router.get("/debug/stats")
async def debug_stats() -> dict:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as session:
        _ = session.execute(select(func.count(Score.id))).scalar() or 0
    # recent last 15m via Python now
    with SessionLocal() as session:
        since = datetime.now(timezone.utc).timestamp() - 900
        recent_count = (
            session.execute(
                select(func.count(Score.id)).where(
                    Score.observed_ts >= datetime.fromtimestamp(since, tz=timezone.utc)
                )
            ).scalar()
            or 0
        )
    stops_count = len(_load_stops())
    return {"stops_count": int(stops_count), "recent_scores": int(recent_count), "now": datetime.now(timezone.utc).isoformat()}
