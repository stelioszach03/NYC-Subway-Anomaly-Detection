"""Idempotent offline feature/evaluation worker; no network or paid services.

Refresh compact features and safe status every five minutes; evaluate at most
hourly. Read the raw archive/immutable daily Parquet without changing either.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from datetime import datetime, timezone

from evaluation.temporal import (
    ALGORITHMS,
    EvaluationConfig,
    OnlineLinear,
    SCHEMA,
    TARGET_NAME,
    evaluate_store,
    feature_vector,
)
from worker.history import archive_status
from worker.temporal_features import (
    BIN_SECONDS,
    FeatureStore,
    LegacyAvailabilityUnavailable,
    canonical,
    file_sha,
    parquet_windows,
    raw_windows,
)


def atomic_json(path, value, *, public=False):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o644 if public else 0o600)
    temporary.replace(path)


def public_path(state):
    directory = state / "public"
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    os.chmod(directory, 0o755)
    return directory / "summary.json"


def source_manifest():
    root = Path(__file__).parents[1]
    names = (
        "worker/temporal_evaluation.py",
        "evaluation/temporal.py",
        "worker/temporal_features.py",
        "worker/history_time.py",
        "worker/history_export.py",
        "worker/history.py",
    )
    files = {name: file_sha(root / name) for name in names}
    return {"files": files, "sha256": hashlib.sha256(canonical(files)).hexdigest()}


def ingest(store, history, cutoff, deadline, *, max_export_days=2):
    imported = []
    pending = []
    export_root = history / "parquet"
    for day in sorted(export_root.glob("????-??-??")):
        if not day.is_dir() or day.is_symlink() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.name):
            continue
        manifest = json.loads((day / "manifest.json").read_text())
        previous = store.db.execute("SELECT sha256 FROM exports WHERE day=?", (day.name,)).fetchone()
        if previous:
            if previous[0] != manifest["sha256"]:
                raise ValueError("Previously ingested immutable Parquet identity changed")
        else:
            pending.append((day, manifest))
    for day, manifest in pending[:max_export_days]:
        status = "ingested"
        try:
            for window in parquet_windows(day, deadline=deadline):
                if window["window_end"] <= cutoff:
                    store.record(window)
        except LegacyAvailabilityUnavailable:
            status = "unusable_missing_availability"
        with store.db:
            store.db.execute("INSERT INTO exports VALUES (?,?,?)", (day.name, manifest["sha256"], status))
        imported.append(day.name)
    earliest = int(store.metadata("raw_cutoff", cutoff - 86400))
    since = max(earliest, cutoff - 86400)
    since = since // BIN_SECONDS * BIN_SECONDS
    new_windows = 0
    for window in raw_windows(history / "history.sqlite3", since, cutoff, deadline=deadline):
        new_windows += store.record(window)
    store.set_metadata("raw_cutoff", cutoff)
    return {
        "new_export_days": imported,
        "pending_export_days": max(0, len(pending) - len(imported)),
        "new_raw_windows": new_windows,
        "ingested_export_days": store.db.execute("SELECT COUNT(*) FROM exports WHERE state='ingested'").fetchone()[0],
        "unusable_legacy_export_days": store.db.execute(
            "SELECT COUNT(*) FROM exports WHERE state='unusable_missing_availability'"
        ).fetchone()[0],
        "source_policy": "Persistent compact features from verified completed UTC-day Parquet plus completed-window raw tail; raw retention is not the sole long-term dependency",
    }


def current_forecasts(store, report, cutoff, now):
    """Use existing train-only models; refresh their input without fitting labels."""
    if not report.get("readiness", {}).get("public_forecasts_ready") or now - report["cutoff_ts"] > 6 * 3600:
        return []
    windows = store.window_metadata(cutoff - 2 * 86400)
    if not windows or windows[-1]["window_end"] != cutoff or not windows[-1]["complete_fresh_feed_coverage"]:
        return []
    valid = {row["window_end"] for row in windows if row["complete_fresh_feed_coverage"]}
    output = []
    config = EvaluationConfig()
    for group in report.get("groups", []):
        if not group.get("ready"):
            continue
        cohort = group["cohort_platform_ids"]
        source = store.group(group["route_id"], group["direction"], cutoff - 2 * 86400)
        from statistics import median

        values = {
            stamp: median(row["platform_spacing_seconds"][stop] for stop in cohort)
            for stamp, row in source.items()
            if stamp in valid and all(stop in row["platform_spacing_seconds"] for stop in cohort)
        }
        features = feature_vector(cutoff, values)
        if features is None:
            continue
        for item in group["horizons"]:
            if not item["ready"] or (item["test_complete_cohort_pair_coverage"] or 0) < config.min_public_pair_coverage:
                continue
            name = item["selected_algorithm_from_validation"]
            if name not in ALGORITHMS:
                continue
            horizon = item["horizon_seconds"]
            prediction = values[cutoff] if name == "persistence" else values.get(cutoff + horizon - 86400)
            if name == "online_linear":
                model = OnlineLinear(config.learning_rate, config.l2_penalty)
                model.weights = item["weights"]
                prediction = model.predict(features)
            if prediction is not None:
                output.append(
                    {
                        "route_id": group["route_id"],
                        "direction": group["direction"],
                        "horizon_seconds": horizon,
                        "origin_ts": cutoff,
                        "target_ts": cutoff + horizon,
                        "predicted_proxy_seconds": prediction,
                        "algorithm": name,
                        "paired_platform_count": len(cohort),
                        "cohort_coverage_fraction": 1.0,
                        "cohort_sha256": group["cohort_sha256"],
                        "validation_mae_seconds": item["validation"][name]["mae_seconds"],
                        "heldout_test_mae_seconds": item["test"][name]["mae_seconds"],
                    }
                )
    return output


def public_summary(report, health, *, now, cutoff, pipeline, forecasts, artifact_id=None):
    feed_rows = [
        {
            "feed": row["feed"],
            "latest_poll_status": row.get("status"),
            "last_receipt_ts": row.get("observed_ts"),
            "receipt_age_seconds": row.get("last_poll_age_seconds"),
            "source_age_seconds": row.get("current_feed_age_seconds"),
        }
        for row in health.get("feeds", [])
    ]
    collector_ready = len(feed_rows) == 8 and all(
        row["latest_poll_status"] == "ok"
        and row["receipt_age_seconds"] is not None
        and 0 <= row["receipt_age_seconds"] <= 180
        and row["source_age_seconds"] is not None
        and -60 <= row["source_age_seconds"] <= 180
        for row in feed_rows
    )
    readiness = dict(
        report.get("readiness")
        or {"status": "collecting", "public_forecasts_ready": False, "reasons": ["Evaluation not yet available"]}
    )
    readiness["reasons"] = list(readiness.get("reasons", []))
    if not collector_ready:
        readiness["reasons"].append("Collector feeds are missing, stale, future-dated or unsuccessful")
    features_fresh = 0 <= now - cutoff <= 600
    if not features_fresh:
        readiness["reasons"].append("Feature publication is stale")
    if pipeline.get("pending_export_days", 0):
        readiness["reasons"].append("Historical feature ingestion is catching up")
    if not forecasts and readiness.get("public_forecasts_ready"):
        readiness["reasons"].append("No current comparable platform cohort or trained model is ready")
    readiness["public_forecasts_ready"] = bool(
        readiness.get("public_forecasts_ready")
        and collector_ready
        and features_fresh
        and not pipeline.get("pending_export_days")
        and forecasts
    )
    if readiness.get("status") == "ready" and not readiness["public_forecasts_ready"]:
        readiness["status"] = "temporarily_unavailable"
    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "generated_ts": now,
        "valid_until_ts": cutoff + 600,
        "feature_cutoff_ts": cutoff,
        "evaluation_cutoff_ts": report.get("cutoff_ts"),
        "target_name": TARGET_NAME,
        "target_definition": report.get(
            "target_definition",
            "Future median of feed-predicted arrival spacings in a fixed, train-selected platform cohort",
        ),
        "is_observed_train_headway": False,
        "incident_evaluation_available": False,
        "readiness": readiness,
        "coverage": report.get("coverage"),
        "feeds": feed_rows,
        "metrics": report.get("metrics", []),
        "forecasts": forecasts if readiness["public_forecasts_ready"] else [],
        "pipeline": {
            key: pipeline.get(key) for key in ("pending_export_days", "ingested_export_days", "feature_bytes")
        },
        "artifact_id": artifact_id,
        "limitations": report.get(
            "limitations", ["Collection/readiness status is not a forecasting-performance result."]
        ),
    }


def publish_evaluation(directory, report, store, cutoff):
    windows = store.window_metadata(cutoff - EvaluationConfig().evaluation_days * 86400)
    inputs_hash = hashlib.sha256(canonical([(row["window_end"], row["input_sha256"]) for row in windows])).hexdigest()
    sources = source_manifest()
    source_hash = sources["sha256"]
    artifact_id = f"{cutoff}-{inputs_hash[:12]}-{source_hash[:12]}"
    target = directory / artifact_id
    if target.exists():
        manifest = json.loads((target / "provenance.json").read_text())
        if (
            manifest["feature_input_sha256"] != inputs_hash
            or manifest["analysis_source_sha256"] != source_hash
            or file_sha(target / "evaluation.json") != manifest["evaluation_sha256"]
            or file_sha(target / "paired-predictions.jsonl.gz") != manifest["paired_predictions_sha256"]
        ):
            raise ValueError("Existing immutable temporal evidence failed integrity verification")
        return artifact_id
    stage = directory / (".stage-" + artifact_id)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, mode=0o700)
    try:
        pairs = report.get("paired_rows", [])
        with gzip.GzipFile(filename=str(stage / "paired-predictions.jsonl.gz"), mode="wb", mtime=0) as stream:
            for row in pairs:
                stream.write(canonical(row) + b"\n")
        private = {key: value for key, value in report.items() if key != "paired_rows"}
        atomic_json(stage / "evaluation.json", private)
        atomic_json(
            stage / "provenance.json",
            {
                "schema": SCHEMA,
                "artifact_id": artifact_id,
                "feature_input_sha256": inputs_hash,
                "analysis_source_sha256": source_hash,
                "source_manifest": sources,
                "evaluation_sha256": file_sha(stage / "evaluation.json"),
                "paired_predictions_sha256": file_sha(stage / "paired-predictions.jsonl.gz"),
                "paired_predictions": len(pairs),
                "forecast_target": TARGET_NAME,
            },
        )
        stage.rename(target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return artifact_id


def prune_reports(directory, *, keep=48, max_bytes=256 * 1024**2):
    reports = sorted(
        path
        for path in directory.iterdir()
        if path.is_dir() and re.fullmatch(r"\d+-[a-f0-9]{12}-[a-f0-9]{12}", path.name)
    )
    sizes = {path: sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) for path in reports}
    while len(reports) > keep or sum(sizes[path] for path in reports) > max_bytes:
        if len(reports) <= 1:
            raise OSError("Single temporal report exceeds evidence disk cap")
        shutil.rmtree(reports.pop(0))


def run_once(history, state, *, now=None, max_seconds=1200, min_free_bytes=2 * 1024**3):
    if history.resolve() == state.resolve():
        raise ValueError("Temporal state must be separate from the immutable history source")
    live_clock = now is None
    now = int(time.time()) if now is None else int(now)
    cutoff = now // BIN_SECONDS * BIN_SECONDS
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    evidence = state / "runs"
    evidence.mkdir(exist_ok=True)
    with (state / "worker.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for stage in evidence.glob(".stage-*"):
            if stage.is_dir() and not stage.is_symlink():
                shutil.rmtree(stage)
        deadline = time.monotonic() + max_seconds
        store = FeatureStore(state / "features.sqlite3", min_free_bytes=min_free_bytes)
        try:
            store.prune(cutoff - 90 * 86400)
            pipeline = ingest(store, history, cutoff, deadline)
            previous_path = state / "latest-evaluation.json"
            previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
            sources = source_manifest()
            due = (
                previous is None
                or cutoff - previous["cutoff_ts"] >= 3600
                or pipeline["new_export_days"]
                or previous.get("analysis_source_sha256") != sources["sha256"]
            )
            artifact_id = store.metadata("latest_artifact_id")
            if due:
                report = evaluate_store(store, cutoff=cutoff, now=now, deadline=deadline)
                report["analysis_source_sha256"] = sources["sha256"]
                report["source_manifest"] = sources
                artifact_id = publish_evaluation(evidence, report, store, cutoff)
                private = {key: value for key, value in report.items() if key != "paired_rows"}
                atomic_json(previous_path, private)
                store.set_metadata("latest_artifact_id", artifact_id)
                prune_reports(evidence)
            else:
                report = previous
            publish_now = int(time.time()) if live_clock else now
            forecasts = current_forecasts(store, report, cutoff, publish_now)
            pipeline["feature_bytes"] = store.disk_bytes()
            health = archive_status(history, now=publish_now)
            summary = public_summary(
                report,
                health,
                now=publish_now,
                cutoff=cutoff,
                pipeline=pipeline,
                forecasts=forecasts,
                artifact_id=artifact_id,
            )
            atomic_json(public_path(state), summary, public=True)
            store.prune(cutoff - 90 * 86400)
            return summary
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path, default=Path("/var/lib/mta-history"))
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "var/temporal")))
    parser.add_argument("--max-seconds", type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.max_seconds <= 1200:
        parser.error("The worker deadline must be 1-1200 seconds")
    try:
        result = run_once(args.history_dir, args.state_dir, max_seconds=args.max_seconds)
    except BlockingIOError:
        print(json.dumps({"status": "already_running", "action": "skipped_without_changing_public_status"}))
        return
    except Exception as error:
        args.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(
            public_path(args.state_dir),
            {
                "schema": SCHEMA,
                "generated_ts": int(time.time()),
                "target_name": TARGET_NAME,
                "readiness": {
                    "status": "error",
                    "public_forecasts_ready": False,
                    "reasons": ["Offline temporal worker could not complete; inspect private service logs"],
                },
                "forecasts": [],
                "metrics": [],
                "error_category": type(error).__name__,
            },
            public=True,
        )
        raise
    print(
        json.dumps({"schema": result["schema"], "readiness": result["readiness"], "artifact_id": result["artifact_id"]})
    )


if __name__ == "__main__":
    main()
