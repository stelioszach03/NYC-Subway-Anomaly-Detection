"""Feature engineering utilities for headway-based anomaly features.

Functions here query recent headway observations from the Scores table
and compute grouped robust statistics (median and MAD) per
``(route_id, stop_id, hour_of_day)`` over a sliding window.

Exports:
- get_features_batch(window_sec=300, return_df=True)
  -> pandas DataFrame with columns: route_id, stop_id, hour, headway_sec, median, mad
  or an iterator of dicts if return_df=False.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine


log = get_logger(__name__)


def _fetch_headways(window_sec: int) -> pd.DataFrame:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)

    with SessionLocal() as session:
        stmt = (
            select(Score.route_id, Score.stop_id, Score.observed_ts, Score.headway_sec)
            .where(Score.observed_ts >= cutoff)
            .where(Score.headway_sec.is_not(None))
        )
        rows = session.execute(stmt).all()

    if not rows:
        return pd.DataFrame(columns=["route_id", "stop_id", "observed_ts", "headway_sec", "hour"])

    df = pd.DataFrame(rows, columns=["route_id", "stop_id", "observed_ts", "headway_sec"])  # type: ignore[arg-type]
    # Keep positive headways only
    df["headway_sec"] = pd.to_numeric(df["headway_sec"], errors="coerce")
    df = df[df["headway_sec"].notna() & (df["headway_sec"] > 0)]
    if df.empty:
        return pd.DataFrame(columns=["route_id", "stop_id", "observed_ts", "headway_sec", "hour"])
    # Ensure timezone-aware and derive hour-of-day (UTC)
    if not pd.api.types.is_datetime64_any_dtype(df["observed_ts"]):
        df["observed_ts"] = pd.to_datetime(df["observed_ts"], utc=True)
    elif df["observed_ts"].dt.tz is None:
        df["observed_ts"] = df["observed_ts"].dt.tz_localize("UTC")
    df["hour"] = df["observed_ts"].dt.hour.astype(int)
    return df[["route_id", "stop_id", "observed_ts", "headway_sec", "hour"]]


def _median_mad(group: pd.Series) -> Tuple[float, float]:
    x = pd.to_numeric(group, errors="coerce").dropna().values.astype(float)
    if x.size == 0:
        return float("nan"), float("nan")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return med, mad


def _compute_stats(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["route_id", "stop_id", "hour"])  # per hour bucket
    stats = grouped["headway_sec"].agg(
        median=lambda s: float(np.median(pd.to_numeric(s, errors="coerce").dropna().values.astype(float))),
        mad=lambda s: float(
            np.median(
                np.abs(
                    pd.to_numeric(s, errors="coerce").dropna().values.astype(float)
                    - np.median(pd.to_numeric(s, errors="coerce").dropna().values.astype(float))
                )
            )
        ),
    )
    stats = stats.reset_index()
    return stats


def get_features_batch(window_sec: int = 300, return_df: bool = True) -> pd.DataFrame | Iterator[Dict]:
    """Return recent headway features for online model input.

    Columns per row: route_id, stop_id, hour, headway_sec, median, mad.
    If return_df is False, returns an iterator of dicts.
    """
    df = _fetch_headways(window_sec)
    if df.empty:
        log.info("no headway rows found for window_sec={}", window_sec)
        return pd.DataFrame(columns=["route_id", "stop_id", "hour", "headway_sec", "median", "mad"]) if return_df else iter(())

    stats = _compute_stats(df)
    out = df.merge(stats, on=["route_id", "stop_id", "hour"], how="left")
    # After merge, headway_sec may be suffixed; normalize name
    if "headway_sec" not in out.columns:
        if "headway_sec_x" in out.columns:
            out = out.rename(columns={"headway_sec_x": "headway_sec"})
        if "headway_sec_y" in out.columns:
            out = out.drop(columns=["headway_sec_y"])
    out = out[["route_id", "stop_id", "hour", "headway_sec", "median", "mad"]]

    if return_df:
        return out

    def _gen() -> Iterator[Dict]:
        for row in out.itertuples(index=False):
            yield {
                "route_id": row.route_id,
                "stop_id": row.stop_id,
                "hour": int(row.hour),
                "headway_sec": float(row.headway_sec) if row.headway_sec == row.headway_sec else None,  # NaN check
                "median": float(row.median) if row.median == row.median else None,
                "mad": float(row.mad) if row.mad == row.mad else None,
            }

    return _gen()


def latest_batch_for_training(limit: int = 128) -> list[Dict]:
    """
    Query oldest unscored rows and produce feature rows:
    {id, route_id, stop_id, headway_sec, hour}.
    """
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    rows: list[Dict] = []
    with SessionLocal() as session:
        stmt = (
            select(
                Score.id,
                Score.route_id,
                Score.stop_id,
                Score.observed_ts,
                Score.headway_sec,
            )
            .where(Score.headway_sec.is_not(None))
            .where(Score.predicted_headway_sec.is_(None))
            .order_by(Score.observed_ts.asc())
            .limit(limit)
        )
        data = session.execute(stmt).all()
        for row_id, route_id, stop_id, ts, headway in data:
            hour = (pd.Timestamp(ts).tz_convert("UTC") if hasattr(ts, 'tzinfo') and ts.tzinfo else pd.Timestamp(ts, tz='UTC')).hour
            rows.append({
                "id": int(row_id),
                "route_id": route_id,
                "stop_id": stop_id,
                "hour": int(hour),
                "headway_sec": float(headway) if headway is not None else 0.0,
            })
    return rows
