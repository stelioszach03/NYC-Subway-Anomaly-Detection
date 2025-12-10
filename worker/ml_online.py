"""Online learning loop for subway headway anomaly scoring.

Design:
- Collector writes raw `headway_sec` rows.
- Trainer scores only rows that do not yet have `predicted_headway_sec`.
- Model state is persisted to disk (pickle + telemetry json).
- Drift (ADWIN over absolute residuals) triggers model reset.
- Self-supervised calibration maps residuals to anomaly scores using rolling quantiles.
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

import numpy as np
from river import anomaly, linear_model, preprocessing
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine
from .drift import DriftMonitor, save_model
from .features import feature_vector_from_row, latest_batch_for_training, reason_candidates


log = get_logger(__name__)
DEFAULT_MODELS_DIR = "/data/gtfs/models"
TELEMETRY_FILENAME = "telemetry.json"


@dataclass
class ModelTelemetry:
    rows_seen: int = 0
    rows_updated: int = 0
    drift_events: int = 0
    mae_ema: float = 0.0
    residual_q90: float = 0.0
    residual_q99: float = 0.0
    last_batch_processed: int = 0
    unscored_backlog: int = 0
    last_run_utc: str | None = None


@dataclass
class ModelBundle:
    reg: object
    hst: anomaly.HalfSpaceTrees
    drift: DriftMonitor
    telemetry: ModelTelemetry
    residual_buffer: list[float]


def _new_drift_monitor() -> DriftMonitor:
    monitor = DriftMonitor(adwin=None)  # type: ignore[arg-type]
    monitor.reset()
    return monitor


def new_bundle() -> ModelBundle:
    reg = preprocessing.StandardScaler() | linear_model.PARegressor()
    hst = anomaly.HalfSpaceTrees(seed=42)
    return ModelBundle(
        reg=reg,
        hst=hst,
        drift=_new_drift_monitor(),
        telemetry=ModelTelemetry(),
        residual_buffer=[],
    )


def _bundle_from_object(obj: object) -> Optional[ModelBundle]:
    if isinstance(obj, ModelBundle):
        if not hasattr(obj, "telemetry") or obj.telemetry is None:
            obj.telemetry = ModelTelemetry()
        if not hasattr(obj, "drift") or obj.drift is None:
            obj.drift = _new_drift_monitor()
        if not hasattr(obj, "residual_buffer") or obj.residual_buffer is None:
            obj.residual_buffer = []
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

    residual_buffer = getattr(obj, "residual_buffer", None)
    if not isinstance(residual_buffer, list):
        residual_buffer = []

    return ModelBundle(reg=reg, hst=hst, drift=drift, telemetry=telemetry, residual_buffer=residual_buffer)


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


def _online_context_features(item: dict[str, object], residual: float) -> dict[str, float]:
    return {
        "residual": float(residual),
        "hour": float(item.get("hour", 0.0) or 0.0),
        "is_peak": float(item.get("is_peak", 0.0) or 0.0),
        "rolling_zscore": float(item.get("rolling_zscore", 0.0) or 0.0),
        "station_baseline_deviation": float(item.get("station_baseline_deviation", 0.0) or 0.0),
        "feed_delay_sec": float(item.get("feed_delay_sec", 0.0) or 0.0),
    }


def _context_deviation_score(item: dict[str, object]) -> float:
    rolling = max(float(item.get("rolling_zscore", 0.0) or 0.0), 0.0) / 3.5
    station = max(float(item.get("station_baseline_deviation", 0.0) or 0.0), 0.0) / 3.0
    quantile = max(float(item.get("quantile_band_deviation", 0.0) or 0.0), 0.0) / 2.75
    trend = max(float(item.get("lag_ratio", 1.0) or 1.0) - 1.0, 0.0) / 1.2
    delay = float(item.get("feed_delay_sec", 0.0) or 0.0) / 120.0
    weather = float(item.get("weather_severity", 0.0) or 0.0) / 3.0
    service = float(item.get("service_alert_active", 0.0) or 0.0) * 0.35
    return _clip01(0.28 * rolling + 0.26 * station + 0.18 * quantile + 0.13 * trend + 0.08 * delay + 0.04 * weather + 0.03 * service)


def _summarize_reasons(item: dict[str, object]) -> list[dict[str, float | str]]:
    reasons = [candidate for candidate in reason_candidates(item) if float(candidate.get("score", 0.0)) >= 0.3]
    return reasons[:3]


def _row_by_id(session, score_id: int) -> Optional[Score]:
    try:
        return session.get(Score, int(score_id))
    except Exception:
        return None


def _trim_residual_buffer(buf: list[float], max_len: int = 8000) -> None:
    if len(buf) > max_len:
        del buf[:-max_len]


def _self_supervised_residual_score(
    abs_residual: float,
    ema_scale: float,
    residual_buffer: list[float],
) -> tuple[float, float, float]:
    if abs_residual <= 0:
        return 0.0, 0.0, 0.0

    if len(residual_buffer) >= 64:
        arr = np.asarray(residual_buffer, dtype=float)
        q50 = float(np.percentile(arr, 50.0))
        q90 = float(np.percentile(arr, 90.0))
        q99 = float(np.percentile(arr, 99.0))
        spread = max(q99 - q50, 1.0)
        score = _clip01((abs_residual - q50) / spread)
        return score, q90, q99

    scale = max(ema_scale, 1.0)
    score = _clip01(abs_residual / (3.5 * scale))
    return score, 0.0, 0.0


def _query_unscored_backlog(session) -> int:
    return int(
        session.execute(
            select(func.count(Score.id))
            .where(Score.headway_sec.is_not(None))
            .where(Score.predicted_headway_sec.is_(None))
        ).scalar()
        or 0
    )


def score_feature_row(bundle: ModelBundle, item: dict[str, object], learn: bool = True) -> dict[str, object]:
    """Score a single enriched observation using the current online learners."""
    y = float(item.get("headway_sec", 0.0) or 0.0)
    if y <= 0:
        raise ValueError("headway_sec must be positive")

    x = feature_vector_from_row(item)
    baseline_prediction = float(item.get("rolling_mean_6", y) or y)
    try:
        reg_prediction = bundle.reg.predict_one(x)
        if reg_prediction is None:
            y_hat = baseline_prediction
        else:
            y_hat = 0.65 * float(reg_prediction) + 0.35 * baseline_prediction
    except Exception:
        y_hat = baseline_prediction

    residual = float(y - y_hat)
    abs_residual = abs(residual)

    if bundle.telemetry.rows_seen == 0:
        bundle.telemetry.mae_ema = abs_residual
    else:
        bundle.telemetry.mae_ema = 0.92 * bundle.telemetry.mae_ema + 0.08 * abs_residual

    ssl_score, q90, q99 = _self_supervised_residual_score(
        abs_residual=abs_residual,
        ema_scale=bundle.telemetry.mae_ema,
        residual_buffer=bundle.residual_buffer,
    )

    hst_context = _online_context_features(item, residual=residual)
    try:
        hst_score = float(bundle.hst.score_one(hst_context))
        if learn:
            bundle.hst.learn_one(hst_context)
    except Exception:
        hst_score = 0.0

    relative_error_score = _clip01(abs_residual / max(abs(y_hat), baseline_prediction, 120.0))
    context_score = _context_deviation_score(item)
    station_score = _clip01(max(float(item.get("station_baseline_deviation", 0.0) or 0.0), 0.0) / 2.8)
    trend_score = _clip01(max(float(item.get("lag_ratio", 1.0) or 1.0) - 1.0, 0.0) / 1.0)
    quantile_score = _clip01(max(float(item.get("quantile_band_deviation", 0.0) or 0.0), 0.0) / 2.2)
    anomaly_score = _clip01(
        0.28 * ssl_score
        + 0.18 * _clip01(hst_score)
        + 0.16 * relative_error_score
        + 0.22 * context_score
        + 0.10 * station_score
        + 0.06 * trend_score
    )
    anomaly_score = max(anomaly_score, _clip01(0.62 * station_score + 0.38 * quantile_score))

    drifted = False
    if learn:
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
        bundle.residual_buffer.append(abs_residual)
        _trim_residual_buffer(bundle.residual_buffer)
        bundle.telemetry.rows_seen += 1

    reasons = _summarize_reasons(item)
    return {
        "predicted_headway_sec": float(y_hat),
        "residual": float(residual),
        "anomaly_score": float(anomaly_score),
        "ssl_score": float(ssl_score),
        "hst_score": float(_clip01(hst_score)),
        "relative_error_score": float(relative_error_score),
        "context_score": float(context_score),
        "station_score": float(station_score),
        "trend_score": float(trend_score),
        "quantile_score": float(quantile_score),
        "residual_q90": float(q90),
        "residual_q99": float(q99),
        "drifted": bool(drifted),
        "reasons": reasons,
        "feature_vector": x,
    }


def process_once(
    models_dir: Optional[str] = None,
    batch_limit: int = 1024,
    max_batches: int = 4,
) -> int:
    """Score the oldest unscored rows and persist updated model state."""
    target_models_dir = models_dir or os.environ.get("MODELS_DIR", DEFAULT_MODELS_DIR)
    bundle = load_latest_bundle(target_models_dir) if target_models_dir else None
    if bundle is None:
        bundle = new_bundle()

    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    now_utc = datetime.now(timezone.utc)
    total_updated = 0
    q90_latest = bundle.telemetry.residual_q90
    q99_latest = bundle.telemetry.residual_q99

    chunk_size = max(64, int(batch_limit))
    loops = max(1, int(max_batches))

    for _ in range(loops):
        batch = latest_batch_for_training(limit=chunk_size)
        if not batch:
            break

        updated_batch = 0
        with SessionLocal() as session:
            for item in batch:
                score_id = int(item.get("id"))
                y = float(item.get("headway_sec", 0.0))
                if y <= 0:
                    continue

                result = score_feature_row(bundle, item, learn=True)
                q90 = float(result.get("residual_q90", 0.0) or 0.0)
                q99 = float(result.get("residual_q99", 0.0) or 0.0)
                if q90 > 0:
                    q90_latest = q90
                if q99 > 0:
                    q99_latest = q99

                row = _row_by_id(session, score_id)
                if row is None:
                    continue
                row.headway_sec = float(y)
                row.predicted_headway_sec = float(result["predicted_headway_sec"])
                row.residual = float(result["residual"])
                row.anomaly_score = float(result["anomaly_score"])
                row.window_sec = row.window_sec or 300
                updated_batch += 1

            session.commit()

        total_updated += int(updated_batch)
        bundle.telemetry.last_batch_processed = int(updated_batch)

        # Queue drained for now.
        if len(batch) < chunk_size:
            break

    with SessionLocal() as session:
        bundle.telemetry.unscored_backlog = _query_unscored_backlog(session)

    bundle.telemetry.rows_updated += int(total_updated)
    bundle.telemetry.residual_q90 = float(q90_latest)
    bundle.telemetry.residual_q99 = float(q99_latest)
    bundle.telemetry.last_run_utc = now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")

    if target_models_dir:
        try:
            save_model(target_models_dir, bundle)
            _write_telemetry_json(target_models_dir, bundle.telemetry)
        except Exception as e:
            log.warning("failed to persist bundle: {}", repr(e))

    return total_updated


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Online anomaly learner for subway headways")
    parser.add_argument("--tick", type=int, default=10, help="Seconds between cycles")
    parser.add_argument("--batch-limit", type=int, default=1024, help="Rows scored per batch")
    parser.add_argument("--max-batches", type=int, default=4, help="Max batches per cycle")
    parser.add_argument(
        "--models-dir",
        type=str,
        default=DEFAULT_MODELS_DIR,
        help="Directory to store rotated models and telemetry json",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.models_dir, exist_ok=True)
    log.info(
        "ml_online starting: tick={}s batch_limit={} max_batches={} models_dir={}",
        args.tick,
        args.batch_limit,
        args.max_batches,
        args.models_dir,
    )
    while True:
        try:
            n = process_once(
                models_dir=args.models_dir,
                batch_limit=args.batch_limit,
                max_batches=args.max_batches,
            )
            log.info("processed {} rows; sleeping {}s", n, args.tick)
        except Exception as e:
            log.warning("ml_online cycle error: {}", repr(e))
        time.sleep(max(1, int(args.tick)))


if __name__ == "__main__":
    main()
