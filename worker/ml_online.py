"""Online learning loop for subway headway anomaly scoring.

Design:
- Collector writes raw `headway_sec` rows.
- Trainer scores only rows that do not yet have `predicted_headway_sec`.
- Model state is persisted to disk (pickle + telemetry json).
- Drift (ADWIN over absolute residuals) triggers model reset.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from river import anomaly, linear_model, preprocessing
from sqlalchemy.orm import sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine
from .drift import DriftMonitor, save_model
from .features import latest_batch_for_training


log = get_logger(__name__)
DEFAULT_MODELS_DIR = "/data/gtfs/models"
TELEMETRY_FILENAME = "telemetry.json"


@dataclass
class ModelTelemetry:
    rows_seen: int = 0
    rows_updated: int = 0
    drift_events: int = 0
    mae_ema: float = 0.0
    last_run_utc: str | None = None


@dataclass
class ModelBundle:
    reg: object
    hst: anomaly.HalfSpaceTrees
    drift: DriftMonitor
    telemetry: ModelTelemetry


def _new_drift_monitor() -> DriftMonitor:
    monitor = DriftMonitor(adwin=None)  # type: ignore[arg-type]
    monitor.reset()
    return monitor


def new_bundle() -> ModelBundle:
    reg = preprocessing.StandardScaler() | linear_model.PARegressor()
    hst = anomaly.HalfSpaceTrees(seed=42)
    return ModelBundle(reg=reg, hst=hst, drift=_new_drift_monitor(), telemetry=ModelTelemetry())


def _bundle_from_object(obj: object) -> Optional[ModelBundle]:
    if isinstance(obj, ModelBundle):
        if not hasattr(obj, "telemetry") or obj.telemetry is None:
            obj.telemetry = ModelTelemetry()
        if not hasattr(obj, "drift") or obj.drift is None:
            obj.drift = _new_drift_monitor()
        return obj

    # Backward compatibility for older pickle payloads
    reg = getattr(obj, "reg", None)
    hst = getattr(obj, "hst", None)
    if reg is None or hst is None:
        return None

    drift = getattr(obj, "drift", None)
    if not isinstance(drift, DriftMonitor):
        drift = _new_drift_monitor()

    telemetry = getattr(obj, "telemetry", None)
    if not isinstance(telemetry, ModelTelemetry):
        telemetry = ModelTelemetry()

    return ModelBundle(reg=reg, hst=hst, drift=drift, telemetry=telemetry)


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
        bundle = _bundle_from_object(obj)
        if bundle is None:
            return None
        log.info("loaded model bundle: {}", path)
        return bundle
    except Exception as e:
        log.warning("failed to load bundle: {}", repr(e))
        return None


def _write_telemetry_json(models_dir: str, telemetry: ModelTelemetry) -> None:
    try:
        os.makedirs(models_dir, exist_ok=True)
        path = os.path.join(models_dir, TELEMETRY_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(telemetry), f, ensure_ascii=True, indent=2)
    except Exception as e:
        log.warning("failed to persist telemetry json: {}", repr(e))


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _feature_pack(route_id: str, stop_id: str, hour: int) -> dict[str, float]:
    # Hash-based categorical proxies keep feature vector numeric and lightweight.
    route_hash = (abs(hash(route_id)) % 997) / 997.0
    stop_hash = (abs(hash(stop_id)) % 4093) / 4093.0
    return {
        "hour": float(hour),
        "route_hash": float(route_hash),
        "stop_hash": float(stop_hash),
    }


def _row_by_id(session, score_id: int) -> Optional[Score]:
    try:
        return session.get(Score, int(score_id))
    except Exception:
        return None


def process_once(models_dir: Optional[str] = None) -> int:
    """Score newest unscored rows and persist updated model state."""
    batch = latest_batch_for_training(limit=256)
    if not batch:
        return 0

    target_models_dir = models_dir or os.environ.get("MODELS_DIR", DEFAULT_MODELS_DIR)
    bundle = load_latest_bundle(target_models_dir) if target_models_dir else None
    if bundle is None:
        bundle = new_bundle()

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    now_utc = datetime.now(timezone.utc)
    updated = 0
    with SessionLocal() as session:
        for item in batch:
            score_id = int(item.get("id"))
            route_id = str(item.get("route_id", ""))
            stop_id = str(item.get("stop_id", ""))
            hour = int(item.get("hour", 0))
            y = float(item.get("headway_sec", 0.0))
            if y <= 0:
                continue

            x = _feature_pack(route_id=route_id, stop_id=stop_id, hour=hour)
            try:
                y_hat = float(bundle.reg.predict_one(x) or y)
            except Exception:
                y_hat = y
            residual = float(y - y_hat)

            # Adaptive scale: EMA of absolute residual (robust enough for streaming)
            abs_residual = abs(residual)
            if bundle.telemetry.rows_seen == 0:
                bundle.telemetry.mae_ema = abs_residual
            else:
                bundle.telemetry.mae_ema = 0.9 * bundle.telemetry.mae_ema + 0.1 * abs_residual
            scale = max(bundle.telemetry.mae_ema, 1.0)
            normalized = min(abs_residual / (4.0 * scale), 1.0)

            try:
                hst_score = float(bundle.hst.score_one({"residual": residual, "hour": float(hour)}))
                bundle.hst.learn_one({"residual": residual, "hour": float(hour)})
            except Exception:
                hst_score = 0.0

            anomaly_score = _clip01(0.55 * normalized + 0.45 * _clip01(hst_score))

            # Drift handling before learner update to avoid carrying stale state.
            drifted = False
            try:
                drifted = bundle.drift.update(abs_residual)
            except Exception:
                drifted = False
            if drifted:
                bundle.telemetry.drift_events += 1
                bundle.reg = preprocessing.StandardScaler() | linear_model.PARegressor()
                bundle.hst = anomaly.HalfSpaceTrees(seed=42)

            try:
                bundle.reg.learn_one(x, y)
            except Exception:
                pass

            row = _row_by_id(session, score_id)
            if row is None:
                continue
            row.headway_sec = float(y)
            row.predicted_headway_sec = float(y_hat)
            row.residual = float(residual)
            row.anomaly_score = float(anomaly_score)
            row.window_sec = row.window_sec or 300
            updated += 1
            bundle.telemetry.rows_seen += 1

        session.commit()

    bundle.telemetry.rows_updated += int(updated)
    bundle.telemetry.last_run_utc = now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")

    if target_models_dir:
        try:
            save_model(target_models_dir, bundle)
            _write_telemetry_json(target_models_dir, bundle.telemetry)
        except Exception as e:
            log.warning("failed to persist bundle: {}", repr(e))

    return updated


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Online anomaly learner for subway headways")
    parser.add_argument("--tick", type=int, default=30, help="Seconds between cycles")
    parser.add_argument(
        "--models-dir",
        type=str,
        default=DEFAULT_MODELS_DIR,
        help="Directory to store rotated models and telemetry json",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.models_dir, exist_ok=True)
    log.info("ml_online starting: tick={}s models_dir={}", args.tick, args.models_dir)
    while True:
        try:
            n = process_once(models_dir=args.models_dir)
            log.info("processed {} rows; sleeping {}s", n, args.tick)
        except Exception as e:
            log.warning("ml_online cycle error: {}", repr(e))
        time.sleep(max(1, int(args.tick)))


if __name__ == "__main__":
    main()
