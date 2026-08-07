"""Feature engineering utilities for online scoring and replay evaluation.

The project keeps a fast numeric feature path for the River online learner,
but now provides richer operational context:

- hour-of-day and day-of-week
- rush-hour and weekend indicators
- lagged headway changes
- rolling mean / std / quantile context
- station-local baseline deviation
- route-direction encoding
- feed freshness / delayed-update indicators
- optional weather and service-alert hooks
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Iterator, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api.app.core.config import get_settings
from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine


log = get_logger(__name__)

NUMERIC_FEATURE_COLUMNS: tuple[str, ...] = (
    "hour",
    "day_of_week",
    "is_weekend",
    "is_peak",
    "route_hash",
    "stop_hash",
    "direction_code",
    "route_direction_hash",
    "lag_headway_1",
    "lag_headway_2",
    "observation_gap_sec",
    "rolling_mean_6",
    "rolling_std_6",
    "rolling_q10_12",
    "rolling_q50_12",
    "rolling_q90_12",
    "station_median_24",
    "station_mad_24",
    "headway_delta_mean",
    "headway_delta_lag",
    "lag_ratio",
    "rolling_zscore",
    "station_baseline_deviation",
    "quantile_band_deviation",
    "event_lead_sec",
    "feed_delay_sec",
    "stale_update_flag",
    "precipitation_mm",
    "weather_severity",
    "service_alert_active",
    "service_alert_severity",
)

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "hour": "UTC hour-of-day for strong service-period effects.",
    "day_of_week": "Weekday context so weekday commute patterns do not look anomalous at baseline.",
    "is_weekend": "Weekend service patterns differ materially from weekday operations.",
    "is_peak": "Rush-hour indicator for the AM/PM commute windows.",
    "lag_headway_1": "Previous observed headway at the same route-stop pair.",
    "lag_headway_2": "Second-most recent headway for short-memory trend context.",
    "rolling_mean_6": "Recent local moving average for the route-stop headway.",
    "rolling_std_6": "Recent local volatility so large swings score higher only when unusual.",
    "rolling_q10_12": "Lower rolling quantile used to contextualize the current headway band.",
    "rolling_q90_12": "Upper rolling quantile used to contextualize the current headway band.",
    "station_baseline_deviation": "Deviation from the recent station-local baseline, scaled by robust MAD.",
    "feed_delay_sec": "How stale the GTFS event is relative to observation time.",
    "stale_update_flag": "Binary indicator for delayed/stale feed updates.",
    "direction_code": "Direction inferred from stop_id suffix when available (for example N/S).",
    "precipitation_mm": "Optional weather hook for replay or production enrichment.",
    "service_alert_active": "Optional service-alert hook for route-level incident context.",
}


def _safe_hash(value: str, mod: int) -> float:
    """Stable hash of a categorical value into [0, 1).

    Uses blake2b rather than the builtin ``hash``: CPython randomizes string
    hashing per process (PYTHONHASHSEED), so ``hash`` gave a station a
    different feature value after every restart. That made the online model's
    persisted checkpoints inconsistent with freshly computed features and made
    the replay evaluation non-reproducible run to run.
    """

    if not value:
        return 0.0
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return float(int.from_bytes(digest, "big") % mod) / float(mod)


def _direction_from_stop_id(stop_id: str) -> str:
    cleaned = (stop_id or "").strip().upper()
    if not cleaned:
        return "U"
    suffix = cleaned[-1]
    if suffix in {"N", "S", "E", "W"}:
        return suffix
    return "U"


def _direction_code(stop_id: str) -> float:
    direction = _direction_from_stop_id(stop_id)
    return {
        "N": 1.0,
        "S": -1.0,
        "E": 0.5,
        "W": -0.5,
    }.get(direction, 0.0)


def _is_peak(hour: int, day_of_week: int) -> float:
    if day_of_week >= 5:
        return 0.0
    return 1.0 if hour in {7, 8, 9, 16, 17, 18, 19} else 0.0


def _ensure_datetime_utc(series: pd.Series) -> pd.Series:
    out = pd.to_datetime(series, utc=True, errors="coerce")
    if hasattr(out, "dt"):
        return out
    return pd.Series(dtype="datetime64[ns, UTC]")


def _rolling_mad(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    median = float(np.median(arr))
    return float(np.median(np.abs(arr - median)))


@lru_cache(maxsize=4)
def _load_weather_snapshot(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=["observed_ts", "precipitation_mm", "weather_severity"])

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        log.warning("failed to load weather snapshot {}: {}", path, repr(exc))
        return pd.DataFrame(columns=["observed_ts", "precipitation_mm", "weather_severity"])

    if "observed_ts" not in df.columns:
        log.warning("weather snapshot missing observed_ts column: {}", path)
        return pd.DataFrame(columns=["observed_ts", "precipitation_mm", "weather_severity"])

    df = df.copy()
    df["observed_ts"] = _ensure_datetime_utc(df["observed_ts"])
    df["precipitation_mm"] = pd.to_numeric(df.get("precipitation_mm", 0.0), errors="coerce").fillna(0.0)
    df["weather_severity"] = pd.to_numeric(df.get("weather_severity", 0.0), errors="coerce").fillna(0.0)
    return df[["observed_ts", "precipitation_mm", "weather_severity"]].sort_values("observed_ts")


@lru_cache(maxsize=4)
def _load_service_alerts(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        log.warning("failed to load service alerts {}: {}", path, repr(exc))
        return []

    alerts = payload.get("alerts", payload) if isinstance(payload, dict) else payload
    if not isinstance(alerts, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        try:
            start = pd.Timestamp(item.get("start_ts"), tz="UTC") if item.get("start_ts") else None
        except Exception:
            start = None
        try:
            end = pd.Timestamp(item.get("end_ts"), tz="UTC") if item.get("end_ts") else None
        except Exception:
            end = None
        normalized.append(
            {
                "route_id": str(item.get("route_id") or "All"),
                "start_ts": start,
                "end_ts": end,
                "severity": float(item.get("severity") or 1.0),
            }
        )
    return normalized


def _apply_weather_context(df: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    path = settings.WEATHER_SNAPSHOT_PATH or ""
    if not path:
        df["precipitation_mm"] = 0.0
        df["weather_severity"] = 0.0
        return df

    weather = _load_weather_snapshot(path)
    if weather.empty:
        df["precipitation_mm"] = 0.0
        df["weather_severity"] = 0.0
        return df

    merged = pd.merge_asof(
        df.sort_values("observed_ts"),
        weather,
        on="observed_ts",
        direction="backward",
        tolerance=pd.Timedelta("3h"),
    )
    merged["precipitation_mm"] = pd.to_numeric(merged["precipitation_mm"], errors="coerce").fillna(0.0)
    merged["weather_severity"] = pd.to_numeric(merged["weather_severity"], errors="coerce").fillna(0.0)
    return merged.sort_values(["observed_ts", "route_id", "stop_id"]).reset_index(drop=True)


def _apply_service_alert_context(df: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    path = settings.SERVICE_ALERTS_PATH or ""
    alerts = _load_service_alerts(path) if path else []
    if not alerts:
        df["service_alert_active"] = 0.0
        df["service_alert_severity"] = 0.0
        return df

    active_flags: list[float] = []
    severities: list[float] = []
    for row in df.itertuples(index=False):
        active = 0.0
        severity = 0.0
        route_id = str(getattr(row, "route_id", ""))
        observed_ts = getattr(row, "observed_ts")
        for alert in alerts:
            alert_route = alert.get("route_id", "All")
            if alert_route not in {"All", route_id}:
                continue
            start_ts = alert.get("start_ts")
            end_ts = alert.get("end_ts")
            if start_ts is not None and observed_ts < start_ts:
                continue
            if end_ts is not None and observed_ts > end_ts:
                continue
            active = 1.0
            severity = max(severity, float(alert.get("severity") or 1.0))
        active_flags.append(active)
        severities.append(severity)

    df["service_alert_active"] = active_flags
    df["service_alert_severity"] = severities
    return df


def _normalize_rows(df: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "id",
        "route_id",
        "stop_id",
        "observed_ts",
        "event_ts",
        "headway_sec",
        "predicted_headway_sec",
        "stop_name",
    ]
    for col in base_cols:
        if col not in df.columns:
            df[col] = None

    out = df.copy()
    out["route_id"] = out["route_id"].fillna("").astype(str)
    out["stop_id"] = out["stop_id"].fillna("").astype(str)
    out["observed_ts"] = _ensure_datetime_utc(out["observed_ts"])
    out["event_ts"] = _ensure_datetime_utc(out["event_ts"])
    out["headway_sec"] = pd.to_numeric(out["headway_sec"], errors="coerce")
    out = out[out["headway_sec"].notna() & (out["headway_sec"] > 0)].copy()
    out["predicted_headway_sec"] = pd.to_numeric(out["predicted_headway_sec"], errors="coerce")
    return out.sort_values(["observed_ts", "route_id", "stop_id"]).reset_index(drop=True)


def _enrich_group(group: pd.DataFrame) -> pd.DataFrame:
    g = group.sort_values("observed_ts").copy()

    history = g["headway_sec"].shift(1)
    prev_obs = g["observed_ts"].shift(1)
    g["lag_headway_1"] = history.fillna(g["headway_sec"])
    g["lag_headway_2"] = g["headway_sec"].shift(2).fillna(g["lag_headway_1"])
    g["observation_gap_sec"] = (
        (g["observed_ts"] - prev_obs).dt.total_seconds().fillna(g["lag_headway_1"])
    )

    g["rolling_mean_6"] = history.rolling(window=6, min_periods=1).mean().fillna(g["headway_sec"])
    g["rolling_std_6"] = history.rolling(window=6, min_periods=2).std().fillna(0.0)
    g["rolling_q10_12"] = history.rolling(window=12, min_periods=3).quantile(0.10).fillna(g["rolling_mean_6"])
    g["rolling_q50_12"] = history.rolling(window=12, min_periods=3).quantile(0.50).fillna(g["rolling_mean_6"])
    g["rolling_q90_12"] = history.rolling(window=12, min_periods=3).quantile(0.90).fillna(g["rolling_mean_6"])
    g["station_median_24"] = history.rolling(window=24, min_periods=3).median().fillna(g["rolling_mean_6"])
    g["station_mad_24"] = history.rolling(window=24, min_periods=3).apply(_rolling_mad, raw=True).fillna(0.0)

    std_floor = np.maximum(g["rolling_std_6"].to_numpy(dtype=float), 30.0)
    mad_floor = np.maximum(g["station_mad_24"].to_numpy(dtype=float), 30.0)
    quantile_band = np.maximum((g["rolling_q90_12"] - g["rolling_q10_12"]).to_numpy(dtype=float), 45.0)

    g["headway_delta_mean"] = g["headway_sec"] - g["rolling_mean_6"]
    g["headway_delta_lag"] = g["headway_sec"] - g["lag_headway_1"]
    g["lag_ratio"] = g["headway_sec"] / np.maximum(g["lag_headway_1"], 60.0)
    g["rolling_zscore"] = g["headway_delta_mean"] / std_floor
    g["station_baseline_deviation"] = (g["headway_sec"] - g["station_median_24"]) / mad_floor
    g["quantile_band_deviation"] = (g["headway_sec"] - g["rolling_q50_12"]) / quantile_band
    return g


def build_feature_frame(rows: pd.DataFrame | Sequence[dict[str, Any]]) -> pd.DataFrame:
    """Build enriched numeric features from score-like rows.

    Expected columns: `route_id`, `stop_id`, `observed_ts`, `event_ts`, `headway_sec`.
    Optional columns such as `id`, `predicted_headway_sec`, and `stop_name` are preserved.
    """
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    df = _normalize_rows(df)
    if df.empty:
        cols = [
            "id",
            "route_id",
            "stop_id",
            "stop_name",
            "observed_ts",
            "event_ts",
            "headway_sec",
            "predicted_headway_sec",
            *NUMERIC_FEATURE_COLUMNS,
        ]
        return pd.DataFrame(columns=cols)

    df["hour"] = df["observed_ts"].dt.hour.astype(float)
    df["day_of_week"] = df["observed_ts"].dt.dayofweek.astype(float)
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(float)
    df["is_peak"] = [
        _is_peak(int(hour), int(day_of_week))
        for hour, day_of_week in zip(df["hour"].tolist(), df["day_of_week"].tolist())
    ]
    df["route_hash"] = df["route_id"].map(lambda value: _safe_hash(str(value), 997))
    df["stop_hash"] = df["stop_id"].map(lambda value: _safe_hash(str(value), 4093))
    df["direction_code"] = df["stop_id"].map(_direction_code)
    df["route_direction_hash"] = [
        _safe_hash(f"{route}:{_direction_from_stop_id(stop)}", 1237)
        for route, stop in zip(df["route_id"].tolist(), df["stop_id"].tolist())
    ]

    enriched_groups = [_enrich_group(group) for _, group in df.groupby(["route_id", "stop_id"], sort=False)]
    enriched = pd.concat(enriched_groups, ignore_index=True).sort_values(["observed_ts", "route_id", "stop_id"]).reset_index(drop=True)

    event_delta = (enriched["event_ts"] - enriched["observed_ts"]).dt.total_seconds()
    event_delta = event_delta.where(pd.notna(event_delta), 0.0)
    enriched["event_lead_sec"] = event_delta.clip(lower=0.0, upper=7200.0)
    enriched["feed_delay_sec"] = (-event_delta).clip(lower=0.0, upper=7200.0)
    enriched["stale_update_flag"] = (enriched["feed_delay_sec"] > 30.0).astype(float)

    if {"precipitation_mm", "weather_severity"}.issubset(enriched.columns):
        enriched["precipitation_mm"] = pd.to_numeric(enriched["precipitation_mm"], errors="coerce").fillna(0.0)
        enriched["weather_severity"] = pd.to_numeric(enriched["weather_severity"], errors="coerce").fillna(0.0)
    else:
        enriched = _apply_weather_context(enriched)

    if {"service_alert_active", "service_alert_severity"}.issubset(enriched.columns):
        enriched["service_alert_active"] = pd.to_numeric(enriched["service_alert_active"], errors="coerce").fillna(0.0)
        enriched["service_alert_severity"] = pd.to_numeric(enriched["service_alert_severity"], errors="coerce").fillna(0.0)
    else:
        enriched = _apply_service_alert_context(enriched)

    for col in NUMERIC_FEATURE_COLUMNS:
        enriched[col] = pd.to_numeric(enriched[col], errors="coerce").fillna(0.0)

    return enriched


def feature_vector_from_row(row: dict[str, Any]) -> dict[str, float]:
    vector: dict[str, float] = {}
    for col in NUMERIC_FEATURE_COLUMNS:
        value = row.get(col, 0.0)
        try:
            vector[col] = float(value)
        except Exception:
            vector[col] = 0.0
    return vector


def reason_candidates(row: dict[str, Any]) -> list[dict[str, float | str]]:
    candidates = [
        {
            "key": "station_baseline_deviation",
            "label": "station baseline deviation",
            "score": abs(float(row.get("station_baseline_deviation", 0.0))),
        },
        {
            "key": "rolling_zscore",
            "label": "rolling z-score jump",
            "score": abs(float(row.get("rolling_zscore", 0.0))),
        },
        {
            "key": "lag_ratio",
            "label": "headway jump vs previous train",
            "score": abs(float(row.get("lag_ratio", 1.0)) - 1.0) * 2.0,
        },
        {
            "key": "feed_delay_sec",
            "label": "stale feed update",
            "score": float(row.get("feed_delay_sec", 0.0)) / 60.0,
        },
        {
            "key": "precipitation_mm",
            "label": "weather pressure",
            "score": float(row.get("precipitation_mm", 0.0)) / 3.0,
        },
        {
            "key": "service_alert_active",
            "label": "service alert context",
            "score": float(row.get("service_alert_active", 0.0)) * max(float(row.get("service_alert_severity", 1.0)), 1.0),
        },
    ]
    return sorted(candidates, key=lambda item: float(item["score"]), reverse=True)


def _fetch_recent_window(window_sec: int) -> pd.DataFrame:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)

    with SessionLocal() as session:
        stmt = (
            select(
                Score.id,
                Score.route_id,
                Score.stop_id,
                Score.observed_ts,
                Score.event_ts,
                Score.headway_sec,
                Score.predicted_headway_sec,
            )
            .where(Score.observed_ts >= cutoff)
            .where(Score.headway_sec.is_not(None))
            .order_by(Score.observed_ts.asc())
        )
        rows = session.execute(stmt).all()

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        rows,
        columns=[
            "id",
            "route_id",
            "stop_id",
            "observed_ts",
            "event_ts",
            "headway_sec",
            "predicted_headway_sec",
        ],
    )


def get_features_batch(window_sec: int = 300, return_df: bool = True) -> pd.DataFrame | Iterator[Dict[str, Any]]:
    """Return enriched recent rows for debugging, notebooks, and replay diagnostics."""
    frame = build_feature_frame(_fetch_recent_window(window_sec))
    if return_df:
        return frame

    def _iter_rows() -> Iterator[Dict[str, Any]]:
        for row in frame.to_dict(orient="records"):
            yield row

    return _iter_rows()


def latest_batch_for_training(limit: int = 128, history_size: int | None = None) -> list[Dict[str, Any]]:
    """Return the oldest pending rows enriched with recent temporal context.

    The trainer still scores the oldest unscored rows first, but now builds each row
    with route-stop local history and optional external context.
    """
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    history_limit = int(history_size or max(limit * 40, 2000))

    with SessionLocal() as session:
        pending = session.execute(
            select(Score.id, Score.observed_ts)
            .where(Score.headway_sec.is_not(None))
            .where(Score.predicted_headway_sec.is_(None))
            .order_by(Score.observed_ts.asc())
            .limit(limit)
        ).all()
        if not pending:
            return []

        pending_ids = [int(row_id) for row_id, _ in pending]
        max_pending_ts = pending[-1][1]

        history_rows = session.execute(
            select(
                Score.id,
                Score.route_id,
                Score.stop_id,
                Score.observed_ts,
                Score.event_ts,
                Score.headway_sec,
                Score.predicted_headway_sec,
            )
            .where(Score.headway_sec.is_not(None))
            .where(Score.observed_ts <= max_pending_ts)
            .order_by(Score.observed_ts.desc())
            .limit(history_limit)
        ).all()

    if not history_rows:
        return []

    history_df = pd.DataFrame(
        history_rows,
        columns=[
            "id",
            "route_id",
            "stop_id",
            "observed_ts",
            "event_ts",
            "headway_sec",
            "predicted_headway_sec",
        ],
    )

    feature_df = build_feature_frame(history_df)
    if feature_df.empty:
        return []

    pending_set = set(pending_ids)
    pending_rows = feature_df[feature_df["id"].isin(pending_set)].copy()
    if pending_rows.empty:
        return []

    order = {score_id: idx for idx, score_id in enumerate(pending_ids)}
    pending_rows["_sort"] = pending_rows["id"].map(order)
    pending_rows = pending_rows.sort_values("_sort").drop(columns=["_sort"])

    records = pending_rows.to_dict(orient="records")
    out: list[Dict[str, Any]] = []
    for row in records:
        row["id"] = int(row["id"])
        row["headway_sec"] = float(row.get("headway_sec") or 0.0)
        out.append(row)
    return out
