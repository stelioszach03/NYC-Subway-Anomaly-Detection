"""Chronological forecasting of a feed-prediction proxy, with train-only fitting.

All targets come from later retained feed snapshots, not actual train passages.
The validation partition alone chooses the forecast algorithm. Test rows are
never fitted and never select a model. No incident accuracy is manufactured.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import math
import statistics
import time

from worker.temporal_features import BIN_SECONDS, DIRECTION_RULE, canonical

SCHEMA = "mta-temporal-evaluation-v1"
TARGET_NAME = "future feed-predicted arrival-spacing proxy"
ALGORITHMS = ("persistence", "seasonal_24h", "online_linear")


@dataclass(frozen=True)
class EvaluationConfig:
    horizons_seconds: tuple[int, ...] = (900, 1800)
    embargo_seconds: int = 1800
    evaluation_days: int = 28
    feasibility_span_seconds: int = 12 * 3600
    public_span_seconds: int = 14 * 86400
    min_train_pairs: int = 24
    min_validation_pairs: int = 6
    min_test_pairs: int = 6
    max_cohort_platforms: int = 3
    min_training_platform_coverage: float = 0.7
    min_public_pair_coverage: float = 0.8
    min_feed_window_coverage: float = 0.9
    min_groups: int = 2
    learning_rate: float = 0.03
    l2_penalty: float = 0.001
    validation_relative_improvement: float = 0.05


def chronological_split(first, last, config):
    span = last - first
    train_end = (first + int(0.6 * span)) // BIN_SECONDS * BIN_SECONDS
    validation_end = (first + int(0.8 * span)) // BIN_SECONDS * BIN_SECONDS
    return {
        "train_start": first,
        "train_end": train_end,
        "validation_start": train_end + config.embargo_seconds,
        "validation_end": validation_end,
        "test_start": validation_end + config.embargo_seconds,
        "test_end": last,
        "embargo_seconds": config.embargo_seconds,
        "partition_policy": "60/20/20 elapsed-time boundaries; 30-minute post-boundary gaps; targets remain inside each partition",
    }


def partition(origin, horizon, split):
    target = origin + horizon
    for name in ("train", "validation", "test"):
        if split[name + "_start"] <= origin and target <= split[name + "_end"]:
            return name
    return None


class OnlineLinear:
    """Small per-series regularized SGD residual model, fitted only on train."""

    def __init__(self, rate=0.03, penalty=0.001):
        self.weights = [0.0] * 7
        self.rate, self.penalty = rate, penalty
        self.updates = 0
        self.latest_label_time = None

    def predict(self, features):
        residual = sum(w * x for w, x in zip(self.weights, features))
        return min(3600.0, max(0.0, 900.0 * (features[1] + residual)))

    def learn(self, features, target, *, label_time, available_by):
        if label_time > available_by:
            raise ValueError("Future label cannot update the model")
        if self.latest_label_time is not None and label_time < self.latest_label_time:
            raise ValueError("Training labels must mature in chronological order")
        error = max(-2.0, min(2.0, (self.predict(features) - target) / 900.0))
        for index, value in enumerate(features):
            self.weights[index] -= self.rate * (error * value + self.penalty * self.weights[index])
        self.updates += 1
        self.latest_label_time = label_time


def feature_vector(origin, values):
    timestamps = (origin, origin - 900, origin - 1800, origin - 3600)
    if any(stamp not in values for stamp in timestamps):
        return None
    current, lag15, lag30, lag60 = (values[stamp] for stamp in timestamps)
    phase = 2 * math.pi * ((origin % 86400) / 86400)
    return [
        1.0,
        current / 900.0,
        (current - lag15) / 900.0,
        (lag15 - lag30) / 900.0,
        (current - lag60) / 900.0,
        math.sin(phase),
        math.cos(phase),
    ]


def measured_metrics(rows, name):
    usable = [row for row in rows if row["predictions"].get(name) is not None]
    errors = [row["predictions"][name] - row["target_value_seconds"] for row in usable]
    return {
        "n": len(errors),
        "eligible_pairs": len(rows),
        "coverage_fraction": len(errors) / len(rows) if rows else None,
        "mae_seconds": statistics.mean(abs(error) for error in errors) if errors else None,
        "rmse_seconds": math.sqrt(statistics.mean(error * error for error in errors)) if errors else None,
        "bias_seconds": statistics.mean(errors) if errors else None,
    }


def choose_validation_model(rows, config):
    metrics = {name: measured_metrics(rows, name) for name in ALGORITHMS}
    reference = metrics["persistence"]
    if reference["n"] < config.min_validation_pairs:
        return None, metrics
    best = "persistence"
    # An alternative needs identical eligible validation coverage, not an easy
    # seasonal subset; no test statistic participates in this decision.
    for name in ("seasonal_24h", "online_linear"):
        value = metrics[name]
        if (
            value["n"] == reference["n"]
            and value["mae_seconds"] is not None
            and value["mae_seconds"] < metrics[best]["mae_seconds"]
            and value["mae_seconds"] <= reference["mae_seconds"] * (1 - config.validation_relative_improvement)
        ):
            best = name
    return best, metrics


def evaluate_group(route, direction, source, valid_windows, split, config):
    training_windows = {stamp for stamp in valid_windows if split["train_start"] <= stamp <= split["train_end"]}
    counts = Counter(
        stop for stamp, row in source.items() if stamp in training_windows for stop in row["platform_spacing_seconds"]
    )
    cohort = [
        stop
        for stop, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if training_windows and count / len(training_windows) >= config.min_training_platform_coverage
    ][: config.max_cohort_platforms]
    if not cohort:
        return {
            "route_id": route,
            "direction": direction,
            "ready": False,
            "reason": "no_stable_training_platform_cohort",
        }, []
    values = {}
    for stamp, row in source.items():
        spacings = row["platform_spacing_seconds"]
        if stamp in valid_windows and all(stop in spacings for stop in cohort):
            values[stamp] = statistics.median(spacings[stop] for stop in cohort)
    cohort_hash = hashlib.sha256(canonical(cohort)).hexdigest()
    details = {
        "route_id": route,
        "direction": direction,
        "cohort_platform_ids": cohort,
        "cohort_sha256": cohort_hash,
        "cohort_size": len(cohort),
        "cohort_selection": "Top at most three platforms by training-window coverage only; both feature and target require the entire fixed cohort",
        "complete_cohort_windows": len(values),
        "source_windows": len(source),
        "horizons": [],
    }
    output_rows = []
    for horizon in config.horizons_seconds:
        model = OnlineLinear(config.learning_rate, config.l2_penalty)
        by_partition = {name: [] for name in ("train", "validation", "test")}
        for origin in sorted(values):
            kind = partition(origin, horizon, split)
            features = feature_vector(origin, values)
            label_time = origin + horizon
            if kind is None or features is None or label_time not in values:
                continue
            target = values[label_time]
            if kind == "train":
                model.learn(features, target, label_time=label_time, available_by=split["train_end"])
                by_partition[kind].append(origin)
                continue
            row = {
                "route_id": route,
                "direction": direction,
                "horizon_seconds": horizon,
                "origin_ts": origin,
                "target_ts": label_time,
                "partition": kind,
                "origin_value_seconds": values[origin],
                "target_value_seconds": target,
                "paired_platform_count": len(cohort),
                "cohort_coverage_fraction": 1.0,
                "cohort_sha256": cohort_hash,
                "source_membership_changed": source[origin]["membership_sha256"]
                != source[label_time]["membership_sha256"],
                "predictions": {
                    "persistence": values[origin],
                    "seasonal_24h": values.get(label_time - 86400),
                    "online_linear": model.predict(features) if model.updates >= config.min_train_pairs else None,
                },
            }
            by_partition[kind].append(row)
        selected, validation = choose_validation_model(by_partition["validation"], config)
        test = {name: measured_metrics(by_partition["test"], name) for name in ALGORITHMS}
        expected_test_origins = max(0, (split["test_end"] - horizon - split["test_start"]) // BIN_SECONDS + 1)
        paired_coverage = len(by_partition["test"]) / expected_test_origins if expected_test_origins else None
        ready = (
            model.updates >= config.min_train_pairs
            and selected is not None
            and len(by_partition["test"]) >= config.min_test_pairs
        )
        for kind in ("validation", "test"):
            for row in by_partition[kind]:
                row["selected_algorithm"] = selected
                row["selected_prediction_seconds"] = row["predictions"].get(selected)
                if ready:
                    output_rows.append(row)
        details["horizons"].append(
            {
                "horizon_seconds": horizon,
                "ready": ready,
                "training_pairs": model.updates,
                "latest_training_label_ts": model.latest_label_time,
                "train_label_cutoff_ts": split["train_end"],
                "validation": validation,
                "test": test,
                "test_expected_origin_slots": expected_test_origins,
                "test_complete_cohort_pair_coverage": paired_coverage,
                "selected_algorithm_from_validation": selected,
                "selected_test": measured_metrics(
                    [
                        {**row, "predictions": {"selected": row["selected_prediction_seconds"]}}
                        for row in by_partition["test"]
                    ],
                    "selected",
                ),
                "weights": model.weights,
                "source_membership_changes_in_test": sum(
                    row["source_membership_changed"] for row in by_partition["test"]
                ),
            }
        )
    details["ready"] = any(row["ready"] for row in details["horizons"])
    return details, output_rows


def evaluate_store(store, *, cutoff, now, config=EvaluationConfig(), deadline=None):
    windows = store.window_metadata(cutoff - config.evaluation_days * 86400)
    if not windows:
        return {
            "schema": SCHEMA,
            "cutoff_ts": cutoff,
            "readiness": {
                "status": "collecting",
                "public_forecasts_ready": False,
                "reasons": ["No retained completed feature windows"],
            },
            "target_name": TARGET_NAME,
            "protocol": asdict(config),
            "groups": [],
            "metrics": [],
            "forecasts": [],
            "paired_rows": [],
        }
    first, last = windows[0]["window_end"], windows[-1]["window_end"]
    span = last - first
    split = chronological_split(first, last, config)
    valid_windows = {row["window_end"] for row in windows if row["complete_fresh_feed_coverage"]}
    expected = (last - first) // BIN_SECONDS + 1
    coverage = len(valid_windows) / expected
    groups, pairs = [], []
    if span >= config.feasibility_span_seconds:
        for route, direction in store.group_keys(first):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Temporal evaluation deadline")
            source = store.group(route, direction, first)
            group, rows = evaluate_group(route, direction, source, valid_windows, split, config)
            groups.append(group)
            pairs.extend(rows)
    ready_groups = sum(group.get("ready", False) for group in groups)
    reasons = []
    if span < config.feasibility_span_seconds:
        reasons.append("Less than 12 hours of retained proxy observations for even short-window feasibility")
    if span < config.public_span_seconds:
        reasons.append("Less than 14 days of retained temporal coverage; no longitudinal claim or public forecast")
    if coverage < config.min_feed_window_coverage:
        reasons.append("Insufficient complete, fresh feed-window coverage")
    if ready_groups < config.min_groups:
        reasons.append("Insufficient stable-cohort train/validation/test pairs")
    if now - last > 900 or cutoff - last > 600:
        reasons.append("Latest feature window is stale")
    forecasts_ready = not reasons
    metrics = []
    for horizon in config.horizons_seconds:
        for kind in ("validation", "test"):
            selected_pairs = [row for row in pairs if row["horizon_seconds"] == horizon and row["partition"] == kind]
            metrics.append(
                {
                    "horizon_seconds": horizon,
                    "partition": kind,
                    "models": {name: measured_metrics(selected_pairs, name) for name in ALGORITHMS},
                    "selected_from_validation": measured_metrics(
                        [
                            {**row, "predictions": {"selected": row["selected_prediction_seconds"]}}
                            for row in selected_pairs
                        ],
                        "selected",
                    ),
                }
            )
    forecasts = []
    if forecasts_ready:
        for group in groups:
            if not group.get("ready"):
                continue
            source = store.group(group["route_id"], group["direction"], first)
            cohort = group["cohort_platform_ids"]
            values = {
                stamp: statistics.median(row["platform_spacing_seconds"][stop] for stop in cohort)
                for stamp, row in source.items()
                if stamp in valid_windows and all(stop in row["platform_spacing_seconds"] for stop in cohort)
            }
            features = feature_vector(last, values)
            if features is None:
                continue
            for item in group["horizons"]:
                if (
                    not item["ready"]
                    or (item["test_complete_cohort_pair_coverage"] or 0) < config.min_public_pair_coverage
                ):
                    continue
                name = item["selected_algorithm_from_validation"]
                if name == "persistence":
                    prediction = values[last]
                elif name == "seasonal_24h":
                    prediction = values.get(last + item["horizon_seconds"] - 86400)
                else:
                    model = OnlineLinear(config.learning_rate, config.l2_penalty)
                    model.weights = item["weights"]
                    prediction = model.predict(features)
                if prediction is None:
                    continue
                forecasts.append(
                    {
                        "route_id": group["route_id"],
                        "direction": group["direction"],
                        "horizon_seconds": item["horizon_seconds"],
                        "origin_ts": last,
                        "target_ts": last + item["horizon_seconds"],
                        "predicted_proxy_seconds": prediction,
                        "algorithm": name,
                        "cohort_sha256": group["cohort_sha256"],
                        "paired_platform_count": len(cohort),
                        "cohort_coverage_fraction": 1.0,
                        "validation_mae_seconds": item["validation"][name]["mae_seconds"],
                        "heldout_test_mae_seconds": item["test"][name]["mae_seconds"],
                    }
                )
    if forecasts_ready and not forecasts:
        reasons.append("No current stable-cohort series satisfies comparable held-out coverage")
        forecasts_ready = False
    return {
        "schema": SCHEMA,
        "cutoff_ts": cutoff,
        "target_name": TARGET_NAME,
        "target_definition": "For a train-selected fixed platform cohort within each route/direction, median gap between the two earliest distinct-trip arrival predictions at a future retained feed snapshot",
        "direction_rule": DIRECTION_RULE,
        "protocol": asdict(config),
        "split": split,
        "coverage": {
            "first_window_ts": first,
            "last_window_ts": last,
            "span_seconds": span,
            "retained_windows": len(windows),
            "expected_window_slots": expected,
            "complete_fresh_window_fraction": coverage,
            "stable_groups_evaluated": ready_groups,
        },
        "readiness": {
            "status": "ready"
            if forecasts_ready
            else "short_window_feasibility"
            if ready_groups >= config.min_groups
            else "collecting",
            "public_forecasts_ready": forecasts_ready,
            "reasons": reasons,
        },
        "groups": groups,
        "metrics": metrics,
        "forecasts": forecasts if forecasts_ready else [],
        "paired_rows": pairs,
        "limitations": [
            "Target is a later feed prediction proxy, not observed train passages, actual headway or passenger waiting time.",
            "Public-feed provenance does not establish official incident labels or operational causality.",
            "Chronological holdouts, delayed train labels and train-only platform cohorts prevent future-label fitting; validation alone selects the algorithm.",
            "Seasonal_24h is missing when no exact 24-hour-lag proxy exists; no default zero or fabricated seasonal accuracy.",
            "Predictions use an offline-trained shadow model; no confidence intervals or broad superiority claims.",
        ],
    }
