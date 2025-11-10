from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import hashlib
from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import distinct, select
from sqlalchemy.orm import sessionmaker

from ..models import Score
from ..storage.session import get_engine
from .stops import _load_routes_from_static


router = APIRouter(prefix="/routes", tags=["routes"])  # /api/routes


class RoutesOut(BaseModel):
    routes: list[str]


@router.get("", response_model=RoutesOut)
async def get_routes(response: Response) -> dict:
    """Return distinct route_ids seen in the last 24h.

    Fallback to static GTFS routes.txt if no scores exist yet.
    """
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    routes: List[str] = []
    with SessionLocal() as session:
        stmt = select(distinct(Score.route_id)).where(Score.observed_ts >= since)
        rows = session.execute(stmt).all()
        routes = [r[0] for r in rows if r and r[0]]

    if not routes:
        routes = _load_routes_from_static()

    routes = sorted(list({r for r in routes if isinstance(r, str) and r.strip()}))
    # caching headers (10 minutes) with weak ETag
    try:
        concat = ",".join(routes).encode("utf-8")
        h = hashlib.sha1(concat).hexdigest()[:16]
        response.headers["ETag"] = f'W/"routes-{len(routes)}-{h}"'
    except Exception:
        pass
    response.headers["Cache-Control"] = "public, max-age=600"
    return {"routes": routes}
