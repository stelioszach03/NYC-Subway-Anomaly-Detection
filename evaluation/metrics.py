from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_K_VALUES = (5, 10, 20)


def _safe_float(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def precision_at_k(df: pd.DataFrame, score_col: str, label_col: str, k: int) -> float:
    if df.empty:
        return 0.0
    top = df.sort_values(score_col, ascending=False).head(min(k, len(df)))
    if top.empty:
        return 0.0
    return float(top[label_col].sum()) / float(len(top))


def recall_at_k(df: pd.DataFrame, score_col: str, label_col: str, k: int) -> float:
    positives = int(df[label_col].sum())
    if positives <= 0:
        return 0.0
    top = df.sort_values(score_col, ascending=False).head(min(k, len(df)))
    return float(top[label_col].sum()) / float(positives)


def false_alarm_rate(df: pd.DataFrame, score_col: str, label_col: str, threshold: float) -> float:
    negatives = df[df[label_col] <= 0]
    if negatives.empty:
        return 0.0
    false_alarms = negatives[negatives[score_col] >= threshold]
    return float(len(false_alarms)) / float(len(negatives))


def mean_reciprocal_rank(df: pd.DataFrame, score_col: str, label_col: str) -> float:
    ranked = df.sort_values(score_col, ascending=False).reset_index(drop=True)
    positive_indexes = ranked.index[ranked[label_col] > 0].tolist()
    if not positive_indexes:
        return 0.0
    return float(np.mean([1.0 / float(idx + 1) for idx in positive_indexes]))


def incident_timing_metrics(
    df: pd.DataFrame,
    score_col: str,
    label_col: str = "label",
    incident_col: str = "incident_id",
    threshold: float = 0.6,
) -> dict[str, float | int]:
    incidents = [incident_id for incident_id in df[incident_col].dropna().unique().tolist() if str(incident_id).strip()]
    if not incidents:
        return {
            "incident_detection_rate": 0.0,
            "detected_incidents": 0,
            "total_incidents": 0,
            "average_lead_time_min": 0.0,
            "average_time_to_detect_min": 0.0,
        }

    detected = 0
    lead_times: list[float] = []
    detection_delays: list[float] = []

    for incident_id in incidents:
        incident_df = df[df[incident_col] == incident_id].sort_values("observed_ts")
        if incident_df.empty:
            continue
        labeled = incident_df[incident_df[label_col] > 0]
        onset = labeled["observed_ts"].min() if not labeled.empty else incident_df["observed_ts"].min()
        detections = incident_df[incident_df[score_col] >= threshold]
        if detections.empty:
            continue
        detected += 1
        first_detection = detections["observed_ts"].min()
        delta_min = float((first_detection - onset).total_seconds() / 60.0)
        if delta_min <= 0:
            lead_times.append(abs(delta_min))
        else:
            detection_delays.append(delta_min)

    return {
        "incident_detection_rate": float(detected) / float(len(incidents)) if incidents else 0.0,
        "detected_incidents": int(detected),
        "total_incidents": int(len(incidents)),
        "average_lead_time_min": float(np.mean(lead_times)) if lead_times else 0.0,
        "average_time_to_detect_min": float(np.mean(detection_delays)) if detection_delays else 0.0,
    }


def evaluate_method(
    df: pd.DataFrame,
    score_col: str,
    label_col: str = "label",
    threshold: float = 0.6,
    k_values: Iterable[int] = DEFAULT_K_VALUES,
) -> dict[str, float | int | dict[str, float]]:
    metrics: dict[str, float | int | dict[str, float]] = {
        "threshold": float(threshold),
        "rows": int(len(df)),
        "positives": int(df[label_col].sum()) if label_col in df.columns else 0,
        "false_alarm_rate": false_alarm_rate(df, score_col, label_col, threshold),
        "mean_reciprocal_rank": mean_reciprocal_rank(df, score_col, label_col),
    }

    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    for k in k_values:
        precision[f"p@{k}"] = precision_at_k(df, score_col, label_col, int(k))
        recall[f"r@{k}"] = recall_at_k(df, score_col, label_col, int(k))
    metrics["precision_at_k"] = precision
    metrics["recall_at_k"] = recall
    metrics.update(incident_timing_metrics(df, score_col, label_col=label_col, threshold=threshold))
    return metrics


def evaluate_methods(
    df: pd.DataFrame,
    method_cols: dict[str, str],
    label_col: str = "label",
    threshold: float = 0.6,
    k_values: Iterable[int] = DEFAULT_K_VALUES,
) -> dict[str, dict[str, float | int | dict[str, float]]]:
    return {
        name: evaluate_method(df, score_col, label_col=label_col, threshold=threshold, k_values=k_values)
        for name, score_col in method_cols.items()
    }
