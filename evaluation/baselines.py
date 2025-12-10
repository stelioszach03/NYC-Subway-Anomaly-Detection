from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def add_baseline_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Add simple transparent baselines used for replay comparison."""
    if frame.empty:
        return frame.copy()

    df = frame.sort_values(["observed_ts", "route_id", "stop_id"]).copy()
    df["baseline_zscore"] = [
        _clip01(max(float(delta), 0.0) / max(float(std), 30.0) / 4.0)
        for delta, std in zip(df["headway_delta_mean"].tolist(), df["rolling_std_6"].tolist())
    ]

    thresholds = np.maximum(df["station_median_24"].to_numpy(dtype=float) * 1.75, df["rolling_q90_12"].to_numpy(dtype=float) * 1.05)
    thresholds = np.maximum(thresholds, 300.0)
    df["baseline_threshold_limit_sec"] = thresholds
    df["baseline_threshold"] = [
        _clip01(max(float(headway) - float(limit), 0.0) / max(float(limit) * 0.75, 60.0))
        for headway, limit in zip(df["headway_sec"].tolist(), thresholds.tolist())
    ]

    df["baseline_ewma"] = 0.0
    df["baseline_ewma_prediction_sec"] = 0.0
    for (_, _), group in df.groupby(["route_id", "stop_id"], sort=False):
        level: float | None = None
        variance = 0.0
        alpha = 0.35
        for idx in group.index:
            current = float(df.at[idx, "headway_sec"])
            prediction = current if level is None else level
            error = current - prediction
            scale = max(math.sqrt(max(variance, 0.0)), 45.0)
            score = _clip01(max(abs(error) - 30.0, 0.0) / (3.0 * scale))

            df.at[idx, "baseline_ewma_prediction_sec"] = float(prediction)
            df.at[idx, "baseline_ewma"] = float(score)

            level = current if level is None else alpha * current + (1.0 - alpha) * level
            variance = alpha * (error ** 2) + (1.0 - alpha) * variance

    return df
