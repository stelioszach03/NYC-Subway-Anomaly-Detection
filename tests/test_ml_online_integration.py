from __future__ import annotations
from datetime import datetime, timedelta, timezone
import random

import pytest
from sqlalchemy.orm import sessionmaker


pytestmark = [pytest.mark.integration]


def _db_reachable() -> bool:
    try:
        from api.app.storage.session import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.timeout(10)
def test_ml_online_updates_scores_once(tmp_path):
    if not _db_reachable():
        pytest.skip("DB not reachable; run docker compose up db or set DB_URL")

    from api.app.models import Base, Score
    from api.app.storage.session import get_engine
    from worker.ml_online import process_once

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    # Seed synthetic rows for a unique route/stop within last 5 minutes
    route_id = f"TST{random.randint(100,999)}"
    stop_id = f"S{random.randint(100,999)}"
    now = datetime.now(timezone.utc)
    rows = []
    for dt in [now - timedelta(seconds=s) for s in (240, 180, 120, 60, 30)]:
        rows.append(
            Score(
                observed_ts=dt,
                event_ts=None,
                route_id=route_id,
                stop_id=stop_id,
                headway_sec=float(random.randint(60, 600)),
                predicted_headway_sec=None,
                anomaly_score=0.0,
                residual=None,
                window_sec=300,
            )
        )

    with SessionLocal() as session:
        session.add_all(rows)
        session.commit()

    updated = process_once(models_dir=str(tmp_path))
    assert updated >= 1

    # Verify latest row updated with anomaly/residual numeric
    with SessionLocal() as session:
        latest = (
            session.query(Score)
            .filter(Score.route_id == route_id, Score.stop_id == stop_id)
            .order_by(Score.observed_ts.desc())
            .first()
        )
        assert latest is not None
        assert isinstance(latest.headway_sec, float)
        assert isinstance(latest.predicted_headway_sec, float)
        assert isinstance(latest.residual, float)
        assert isinstance(latest.anomaly_score, float)
        assert 0.0 <= latest.anomaly_score <= 1.0
