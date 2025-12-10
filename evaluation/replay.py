from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from evaluation.artifacts import write_replay_artifacts
from evaluation.baselines import add_baseline_scores
from evaluation.metrics import evaluate_methods
from worker.features import build_feature_frame
from worker.ml_online import new_bundle, score_feature_row


METHOD_COLUMNS = {
    "online_model": "online_model_score",
    "zscore_baseline": "baseline_zscore",
    "ewma_baseline": "baseline_ewma",
    "threshold_baseline": "baseline_threshold",
}


def load_replay_dataset(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Replay dataset not found: {csv_path}")

    df = pd.read_csv(csv_path)
    required = {"observed_ts", "route_id", "stop_id", "headway_sec"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Replay dataset missing required columns: {', '.join(missing)}")

    df = df.copy()
    df["observed_ts"] = pd.to_datetime(df["observed_ts"], utc=True, errors="coerce")
    df["event_ts"] = pd.to_datetime(df.get("event_ts"), utc=True, errors="coerce")
    df["headway_sec"] = pd.to_numeric(df["headway_sec"], errors="coerce")
    df = df[df["observed_ts"].notna() & df["headway_sec"].notna()].copy()

    for col in (
        "stop_name",
        "incident_id",
        "incident_title",
        "incident_note",
    ):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("")

    for col in ("label", "precipitation_mm", "weather_severity", "service_alert_active", "service_alert_severity"):
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df.sort_values(["observed_ts", "route_id", "stop_id"]).reset_index(drop=True)


def replay_online_model(feature_df: pd.DataFrame) -> pd.DataFrame:
    bundle = new_bundle()
    rows: list[dict[str, Any]] = []

    for row in feature_df.to_dict(orient="records"):
        result = score_feature_row(bundle, row, learn=True)
        output = dict(row)
        output["predicted_headway_sec"] = float(result["predicted_headway_sec"])
        output["residual"] = float(result["residual"])
        output["online_model_score"] = float(result["anomaly_score"])
        output["ssl_score"] = float(result["ssl_score"])
        output["hst_score"] = float(result["hst_score"])
        output["relative_error_score"] = float(result["relative_error_score"])
        output["context_score"] = float(result["context_score"])
        output["reason_details"] = list(result["reasons"])
        output["reason_labels"] = [str(item.get("label")) for item in result["reasons"]]
        rows.append(output)

    return pd.DataFrame(rows)


def run_replay_evaluation(dataset_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    source_df = load_replay_dataset(dataset_path)
    feature_df = build_feature_frame(source_df)
    replay_df = replay_online_model(feature_df)
    scored_df = add_baseline_scores(replay_df)
    metrics = evaluate_methods(scored_df, METHOD_COLUMNS, label_col="label", threshold=0.6)
    summary = write_replay_artifacts(results_df=scored_df, metrics=metrics, out_dir=out_dir, dataset_path=str(dataset_path))
    return {
        "summary": summary,
        "metrics": metrics,
        "results": scored_df,
    }
