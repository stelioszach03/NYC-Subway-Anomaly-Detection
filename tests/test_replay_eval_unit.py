from __future__ import annotations

from pathlib import Path

from evaluation.replay import run_replay_evaluation


SAMPLE_DATASET = Path('evaluation/data/sample_subway_headways.csv')


def test_replay_evaluation_writes_artifacts(tmp_path):
    payload = run_replay_evaluation(SAMPLE_DATASET, tmp_path)

    summary = payload['summary']
    metrics = payload['metrics']
    results = payload['results']

    assert summary['dataset']['rows'] == 216
    assert summary['dataset']['incidents'] == 3
    assert (tmp_path / 'summary.json').exists()
    assert (tmp_path / 'timeline.json').exists()
    assert (tmp_path / 'incidents.json').exists()
    assert (tmp_path / 'events.csv').exists()
    assert (tmp_path / 'plots' / 'overall-scores.svg').exists()

    assert len(results) == 216
    assert metrics['online_model']['incident_detection_rate'] == 1.0
    assert metrics['online_model']['precision_at_k']['p@10'] >= 0.7
    assert metrics['online_model']['recall_at_k']['r@20'] >= 1.0
