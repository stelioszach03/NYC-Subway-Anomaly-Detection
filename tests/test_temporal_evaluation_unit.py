"""Synthetic chronology/cohort checks; never a real transit performance result."""

from copy import deepcopy
import hashlib

import pytest

pytest.importorskip("pyarrow")

# ruff: noqa: E402

from evaluation.temporal import (
    EvaluationConfig,
    OnlineLinear,
    chronological_split,
    choose_validation_model,
    evaluate_group,
    measured_metrics,
    partition,
)
from worker.temporal_features import canonical
from worker.temporal_evaluation import public_summary
from worker.history import FEEDS


def source_series(hours=72):
    return {
        stamp: {
            "platform_spacing_seconds": {
                "A01N": 300 + (stamp // 300 % 12) * 10,
                "A02N": 360 + (stamp // 300 % 12) * 10,
            },
            "membership_sha256": hashlib.sha256(canonical(["A01N", "A02N"])).hexdigest(),
        }
        for stamp in range(300, hours * 3600 + 1, 300)
    }


@pytest.mark.parametrize("horizon", [900, 1800])
def test_15_30_minute_labels_cannot_cross_train_validation_test_boundaries(horizon):
    split = chronological_split(0, 72 * 3600, EvaluationConfig())
    assert partition(split["train_end"] - horizon, horizon, split) == "train"
    assert partition(split["train_end"] - horizon + 300, horizon, split) is None
    assert partition(split["validation_start"] - 300, horizon, split) is None
    assert partition(split["validation_start"], horizon, split) == "validation"
    assert partition(split["validation_end"] - horizon + 300, horizon, split) is None
    assert partition(split["test_start"] - 300, horizon, split) is None
    assert partition(split["test_start"], horizon, split) == "test"
    model = OnlineLinear()
    with pytest.raises(ValueError, match="Future label"):
        model.learn([1, 1, 0, 0, 0, 0, 0], 900, label_time=1800, available_by=1799)


def test_changing_test_targets_cannot_fit_weights_select_platforms_or_choose_model():
    source = source_series()
    config = EvaluationConfig()
    split = chronological_split(min(source), max(source), config)
    baseline, _ = evaluate_group("A", "platform:N", source, set(source), split, config)
    modified = deepcopy(source)
    for stamp, row in modified.items():
        if stamp >= split["test_start"]:
            row["platform_spacing_seconds"] = {"A01N": 1200, "A02N": 1400, "unseen_test_platform": 1}
    altered, _ = evaluate_group("A", "platform:N", modified, set(modified), split, config)
    assert baseline["cohort_platform_ids"] == altered["cohort_platform_ids"]
    for before, after in zip(baseline["horizons"], altered["horizons"], strict=True):
        assert before["weights"] == after["weights"]
        assert before["selected_algorithm_from_validation"] == after["selected_algorithm_from_validation"]
        assert before["validation"] == after["validation"]
        assert before["latest_training_label_ts"] <= split["train_end"]
        assert before["test"] != after["test"]


def test_fixed_cohort_requires_comparable_platform_membership_and_seasonal_stays_null():
    source = source_series(hours=20)
    config = EvaluationConfig()
    split = chronological_split(min(source), max(source), config)
    missing = split["test_start"] + 900
    source[missing]["platform_spacing_seconds"].pop("A02N")
    report, pairs = evaluate_group("A", "platform:N", source, set(source), split, config)
    assert len(report["cohort_platform_ids"]) == 2
    assert not any(row["origin_ts"] == missing or row["target_ts"] == missing for row in pairs)
    assert all(row["paired_platform_count"] == 2 for row in pairs)
    assert all(row["predictions"]["seasonal_24h"] is None for row in pairs)
    assert measured_metrics(pairs, "seasonal_24h")["mae_seconds"] is None


def test_validation_selector_never_promotes_a_better_looking_sparse_seasonal_subset():
    rows = [
        {
            "target_value_seconds": 10,
            "predictions": {"persistence": 12, "online_linear": 20, "seasonal_24h": 10 if index == 0 else None},
        }
        for index in range(10)
    ]
    selected, _ = choose_validation_model(rows, EvaluationConfig())
    assert selected == "persistence"


def test_public_forecasts_are_empty_until_readiness_and_freshness_gates_hold():
    now = 3600
    health = {
        "feeds": [
            {
                "feed": feed,
                "status": "ok",
                "observed_ts": now - 5,
                "last_poll_age_seconds": 5,
                "current_feed_age_seconds": 10,
            }
            for feed in FEEDS
        ]
    }
    report = {
        "cutoff_ts": now,
        "readiness": {
            "status": "short_window_feasibility",
            "public_forecasts_ready": False,
            "reasons": ["Less than 14 days"],
        },
        "metrics": [],
    }
    arguments = dict(now=now, cutoff=now, pipeline={"pending_export_days": 0}, forecasts=[{"fixture": True}])
    result = public_summary(report, health, **arguments)
    assert result["forecasts"] == []
    report["readiness"] = {"status": "ready", "public_forecasts_ready": True, "reasons": []}
    health["feeds"][0]["current_feed_age_seconds"] = 1000
    result = public_summary(report, health, **arguments)
    assert not result["readiness"]["public_forecasts_ready"] and result["forecasts"] == []
