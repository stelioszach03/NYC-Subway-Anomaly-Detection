"""Online learning of headway anomalies.

Pipeline (one-shot process):
- Regressor: StandardScaler -> PassiveAggressiveRegressor to predict headway_sec.
- Residual: actual - predicted.
- Anomaly score: 0.6 * normalized |residual| (MAD) + 0.4 * HalfSpaceTrees score.
- Optionally persist model state to models_dir.

Also includes continuous loop CLI, but exposes process_once(models_dir) for integration tests.
"""
from __future__ import annotations

import argparse
import os
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import numpy as np

from river import anomaly, linear_model, preprocessing
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine
from .drift import DriftMonitor, save_model
from .features import latest_batch_for_training


log = get_logger(__name__)


@dataclass
class ModelBundle:
    reg: object
    hst: anomaly.HalfSpaceTrees
    drift: DriftMonitor


def new_bundle() -> ModelBundle:
    reg = preprocessing.StandardScaler() | linear_model.PARegressor()
    hst = anomaly.HalfSpaceTrees(seed=42)
    drift = DriftMonitor(adwin=None)  # type: ignore[arg-type]
    drift.reset()
    return ModelBundle(reg=reg, hst=hst, drift=drift)


def load_latest_bundle(models_dir: str) -> Optional[ModelBundle]:
    try:
        if not os.path.isdir(models_dir):
            return None
        files = [f for f in os.listdir(models_dir) if f.endswith(".pkl")]
        if not files:
            return None
        files.sort(reverse=True)
        path = os.path.join(models_dir, files[0])
        with open(path, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, ModelBundle):
            log.info("loaded model bundle: {}", path)
            return obj
        return None
    except Exception as e:
        log.warning("failed to load bundle: {}", repr(e))
        return None


def _latest_score_id_for(session, route_id: str, stop_id: str, cutoff_ts: datetime) -> Optional[int]:
    stmt = (
        select(Score.id)
        .where(Score.route_id == route_id, Score.stop_id == stop_id, Score.observed_ts >= cutoff_ts)
        .order_by(Score.observed_ts.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return int(row[0]) if row else None


def process_once(models_dir: Optional[str] = None) -> int:
    """
    Train/predict on the latest small batch and write residual/anomaly_score.
    Returns number of updated rows.
    """
    batch = latest_batch_for_training(limit=128)
    if not batch:
        return 0

    # Regressor & anomaly model
    reg = preprocessing.StandardScaler() | linear_model.PARegressor()
    hst = anomaly.HalfSpaceTrees(seed=42)

    # Robust MAD across batch
    ys = [float(b.get("headway_sec", 0.0)) for b in batch]
    if not ys:
        return 0
    med = float(np.median(ys))
    mad = float(np.median(np.abs(np.array(ys, dtype=float) - med)))
    if mad <= 0:
        std = float(np.std(ys))
        mad = std if std > 0 else 1.0

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    updated = 0
    with SessionLocal() as session:
        for b in batch:
            route_id = str(b.get("route_id", ""))
            stop_id = str(b.get("stop_id", ""))
            hour = int(b.get("hour", 0))
            y = float(b.get("headway_sec", 0.0))
            x = {"hour": hour}
            try:
                y_hat = float(reg.predict_one(x) or 0.0)
            except Exception:
                y_hat = 0.0
            residual = y - y_hat
            # anomaly score
            norm = min(abs(residual) / mad, 10.0) / 10.0
            try:
                hst_score = float(hst.score_one({"residual": residual}))
                hst.learn_one({"residual": residual})
            except Exception:
                hst_score = 0.0
            anomaly_score = 0.6 * norm + 0.4 * max(0.0, min(hst_score, 1.0))

            # learn after scoring
            try:
                reg.learn_one(x, y)
            except Exception:
                pass

            # Update latest row for this (route_id, stop_id)
            sid = _latest_score_id_for(session, route_id, stop_id, datetime.min.replace(tzinfo=timezone.utc))
            if sid is None:
                continue
            obj = session.get(Score, sid)
            if obj is None:
                continue
            obj.residual = float(residual)
            obj.anomaly_score = float(anomaly_score)
            obj.window_sec = obj.window_sec or 300
            updated += 1
        session.commit()

    # Best-effort model persist
    if models_dir:
        try:
            bundle = ModelBundle(reg=reg, hst=hst, drift=DriftMonitor(adwin=None))  # type: ignore[arg-type]
            save_model(models_dir, bundle)
        except Exception:
            pass

    return updated


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Online anomaly learner for headways")
    parser.add_argument("--tick", type=int, default=30, help="Seconds between batches")
    parser.add_argument("--window", type=int, default=300, help="Window seconds to fetch features")
    parser.add_argument("--models-dir", type=str, default="/data/gtfs/models", help="Directory to store rotated models")
    args = parser.parse_args(argv)

    os.makedirs(args.models_dir, exist_ok=True)

    log.info("ml_online starting: tick={}s window={}s", args.tick, args.window)
    while True:
        try:
            # Compatibility: call continuous features-based loop using legacy API
            n = process_once(models_dir=args.models_dir)
            log.info("processed {} rows; sleeping {}s", n, args.tick)
        except Exception as e:
            log.warning("ml_online cycle error: {}", repr(e))
        time.sleep(max(1, int(args.tick)))


if __name__ == "__main__":
    main()
