from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from worker.features import FEATURE_DESCRIPTIONS


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "incident"


def _json_default(value: Any):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _line_svg(points: list[dict[str, Any]], title: str, series: list[tuple[str, str]]) -> str:
    width = 980
    height = 340
    margin_left = 52
    margin_right = 20
    margin_top = 28
    margin_bottom = 36
    inner_w = width - margin_left - margin_right
    inner_h = height - margin_top - margin_bottom
    xs = [idx / max(len(points) - 1, 1) for idx in range(len(points))]

    lines = []
    grid = []
    for tick in range(0, 6):
        y = margin_top + inner_h - (inner_h * tick / 5.0)
        value = tick / 5.0
        grid.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" stroke="#dbe4ef" stroke-width="1" />')
        grid.append(f'<text x="14" y="{y + 4:.1f}" font-size="11" fill="#64748b">{value:.1f}</text>')

    for name, color in series:
        coords: list[str] = []
        for idx, point in enumerate(points):
            x = margin_left + xs[idx] * inner_w
            score = max(0.0, min(1.0, float(point.get(name, 0.0) or 0.0)))
            y = margin_top + inner_h - score * inner_h
            coords.append(f"{x:.1f},{y:.1f}")
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{" ".join(coords)}" />')

    legend = []
    for idx, (name, color) in enumerate(series):
        lx = margin_left + idx * 170
        legend.append(f'<rect x="{lx}" y="{height - 22}" width="12" height="12" rx="3" fill="{color}" />')
        legend.append(f'<text x="{lx + 18}" y="{height - 12}" font-size="12" fill="#334155">{name}</text>')

    labels = []
    if points:
        first = points[0].get("observed_ts", "")
        last = points[-1].get("observed_ts", "")
        labels.append(f'<text x="{margin_left}" y="{height - 8}" font-size="11" fill="#64748b">{first}</text>')
        labels.append(f'<text x="{width - margin_right - 190}" y="{height - 8}" font-size="11" fill="#64748b">{last}</text>')

    return "".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f8fafc" rx="18" />',
            f'<text x="{margin_left}" y="18" font-size="16" font-weight="700" fill="#0f172a">{title}</text>',
            *grid,
            *lines,
            *legend,
            *labels,
            '</svg>',
        ]
    )


def build_snapshot_points(results_df: pd.DataFrame) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for ts, group in results_df.sort_values("observed_ts").groupby("observed_ts", sort=True):
        ranked = group.sort_values("online_model_score", ascending=False)
        top_routes = (
            group.groupby("route_id", dropna=False)["online_model_score"]
            .max()
            .sort_values(ascending=False)
            .head(3)
        )
        top_stops = ranked.head(5)
        incident_rows = group[group["incident_id"].fillna("") != ""]
        incident_id = str(incident_rows["incident_id"].iloc[0]) if not incident_rows.empty else ""
        incident_title = str(incident_rows["incident_title"].iloc[0]) if not incident_rows.empty else ""

        points.append(
            {
                "index": len(points),
                "observed_ts": pd.Timestamp(ts).isoformat(),
                "model_peak_score": float(ranked["online_model_score"].max()),
                "baseline_zscore_peak": float(ranked["baseline_zscore"].max()),
                "baseline_ewma_peak": float(ranked["baseline_ewma"].max()),
                "baseline_threshold_peak": float(ranked["baseline_threshold"].max()),
                "label": int(group["label"].max()),
                "incident_id": incident_id,
                "incident_title": incident_title,
                "top_routes": [
                    {"route_id": route_id, "peak_score": float(score)}
                    for route_id, score in top_routes.items()
                ],
                "top_stops": [
                    {
                        "route_id": str(row.route_id),
                        "stop_id": str(row.stop_id),
                        "stop_name": str(row.stop_name or row.stop_id),
                        "headway_sec": float(row.headway_sec),
                        "predicted_headway_sec": float(row.predicted_headway_sec),
                        "online_model_score": float(row.online_model_score),
                        "baseline_zscore": float(row.baseline_zscore),
                        "baseline_ewma": float(row.baseline_ewma),
                        "baseline_threshold": float(row.baseline_threshold),
                        "reasons": list(row.reason_labels or []),
                    }
                    for row in top_stops.itertuples(index=False)
                ],
            }
        )
    return points


def _incident_plot_rows(incident_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "observed_ts": point["observed_ts"],
            "online_model_score": point.get("model_peak_score", 0.0),
            "baseline_zscore": point.get("baseline_zscore_peak", 0.0),
            "baseline_ewma": point.get("baseline_ewma_peak", 0.0),
            "baseline_threshold": point.get("baseline_threshold_peak", 0.0),
        }
        for point in incident_points
    ]


def write_replay_artifacts(
    *,
    results_df: pd.DataFrame,
    metrics: dict[str, Any],
    out_dir: str | Path,
    dataset_path: str,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    incident_dir = out_path / "incidents"
    plot_dir = out_path / "plots"
    incident_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)

    export_df = results_df.copy()
    export_df["observed_ts"] = export_df["observed_ts"].map(lambda value: pd.Timestamp(value).isoformat())
    export_df["event_ts"] = export_df["event_ts"].map(lambda value: pd.Timestamp(value).isoformat() if pd.notna(value) else None)
    export_df["reason_labels"] = export_df["reason_labels"].map(json.dumps)
    export_df.to_csv(out_path / "events.csv", index=False)

    snapshot_points = build_snapshot_points(results_df)
    (out_path / "timeline.json").write_text(json.dumps({"points": snapshot_points}, indent=2, default=_json_default), encoding="utf-8")

    overall_plot = _line_svg(
        [
            {
                "observed_ts": point["observed_ts"],
                "online_model_score": point["model_peak_score"],
                "baseline_zscore": point["baseline_zscore_peak"],
                "baseline_ewma": point["baseline_ewma_peak"],
                "baseline_threshold": point["baseline_threshold_peak"],
            }
            for point in snapshot_points
        ],
        title="Replay timeline: online model vs baselines",
        series=[
            ("online_model_score", "#0f766e"),
            ("baseline_zscore", "#dc2626"),
            ("baseline_ewma", "#2563eb"),
            ("baseline_threshold", "#9333ea"),
        ],
    )
    (plot_dir / "overall-scores.svg").write_text(overall_plot, encoding="utf-8")

    incidents: list[dict[str, Any]] = []
    non_empty_incidents = [incident_id for incident_id in results_df["incident_id"].dropna().unique().tolist() if str(incident_id).strip()]
    for incident_id in non_empty_incidents:
        incident_rows = results_df[results_df["incident_id"] == incident_id].sort_values("observed_ts")
        if incident_rows.empty:
            continue
        title = str(incident_rows["incident_title"].iloc[0])
        slug = _slugify(str(incident_id))
        start_ts = incident_rows["observed_ts"].min()
        end_ts = incident_rows["observed_ts"].max()
        first_detection = incident_rows[incident_rows["online_model_score"] >= 0.6]["observed_ts"].min()
        labeled_start = incident_rows[incident_rows["label"] > 0]["observed_ts"].min()
        detection_delay_min = 0.0
        if pd.notna(first_detection) and pd.notna(labeled_start):
            detection_delay_min = float((first_detection - labeled_start).total_seconds() / 60.0)

        grouped_points = [
            point
            for point in snapshot_points
            if point.get("incident_id") == incident_id
            or (pd.Timestamp(point["observed_ts"]) >= start_ts and pd.Timestamp(point["observed_ts"]) <= end_ts)
        ]
        plot_rows = _incident_plot_rows(grouped_points)
        (plot_dir / f"{slug}.svg").write_text(
            _line_svg(
                plot_rows,
                title=f"Incident replay: {title}",
                series=[
                    ("online_model_score", "#0f766e"),
                    ("baseline_zscore", "#dc2626"),
                    ("baseline_ewma", "#2563eb"),
                    ("baseline_threshold", "#9333ea"),
                ],
            ),
            encoding="utf-8",
        )

        reason_counts: dict[str, int] = {}
        for labels in incident_rows["reason_labels"].tolist():
            for label in labels or []:
                reason_counts[label] = reason_counts.get(label, 0) + 1
        top_reasons = [label for label, _ in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:3]]

        top_routes = (
            incident_rows.groupby("route_id", dropna=False)["online_model_score"]
            .max()
            .sort_values(ascending=False)
            .head(3)
        )
        top_stops = (
            incident_rows.sort_values("online_model_score", ascending=False)
            .head(5)[["stop_id", "stop_name", "route_id", "online_model_score", "headway_sec", "predicted_headway_sec"]]
            .to_dict(orient="records")
        )

        detail = {
            "incident_id": incident_id,
            "incident_title": title,
            "what_happened": str(incident_rows["incident_note"].iloc[0] or "Representative replay scenario."),
            "window_start": pd.Timestamp(start_ts).isoformat(),
            "window_end": pd.Timestamp(end_ts).isoformat(),
            "peak_score": float(incident_rows["online_model_score"].max()),
            "peak_label": int(incident_rows["label"].max()),
            "detection_delay_min": detection_delay_min,
            "top_reasons": top_reasons,
            "top_routes": [{"route_id": route_id, "peak_score": float(score)} for route_id, score in top_routes.items()],
            "top_stops": top_stops,
            "points": grouped_points,
            "plot_path": f"plots/{slug}.svg",
        }
        (incident_dir / f"{slug}.json").write_text(json.dumps(detail, indent=2, default=_json_default), encoding="utf-8")

        incidents.append(
            {
                "incident_id": incident_id,
                "incident_title": title,
                "window_start": pd.Timestamp(start_ts).isoformat(),
                "window_end": pd.Timestamp(end_ts).isoformat(),
                "peak_score": float(incident_rows["online_model_score"].max()),
                "detection_delay_min": detection_delay_min,
                "top_reasons": top_reasons,
                "affected_routes": [route_id for route_id in top_routes.index.tolist()],
                "detail_path": f"incidents/{slug}.json",
                "plot_path": f"plots/{slug}.svg",
            }
        )

    (out_path / "incidents.json").write_text(json.dumps({"incidents": incidents}, indent=2, default=_json_default), encoding="utf-8")
    (out_path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default), encoding="utf-8")

    summary = {
        "dataset": {
            "path": dataset_path,
            "rows": int(len(results_df)),
            "positive_rows": int(results_df["label"].sum()),
            "routes": int(results_df["route_id"].nunique()),
            "stops": int(results_df["stop_id"].nunique()),
            "incidents": int(len(incidents)),
        },
        "metrics": metrics,
        "feature_highlights": [
            {"feature": feature, "why_it_matters": description}
            for feature, description in FEATURE_DESCRIPTIONS.items()
        ],
        "artifacts": {
            "events_csv": "events.csv",
            "timeline_json": "timeline.json",
            "incidents_json": "incidents.json",
            "overall_plot": "plots/overall-scores.svg",
        },
        "notes": [
            "Replay metrics are based on representative labeled scenarios, not official MTA incident annotations.",
            "The online River model is replayed sequentially to preserve the same fast scoring path used in live operation.",
        ],
    }
    (out_path / "summary.json").write_text(json.dumps(summary, indent=2, default=_json_default), encoding="utf-8")
    return summary
