import json
import time
import fcntl
import stat

import pytest

pytest.importorskip("pyarrow")

# ruff: noqa: E402

from worker.history import HistoryArchive, Limits
from worker.temporal_evaluation import ingest, publish_evaluation, run_once, source_manifest
from worker.temporal_features import FeatureStore
from worker.history import FEEDS, payload_metadata
from worker.history_export import export_completed
from test_temporal_features_unit import payload


def test_empty_archive_is_honestly_collecting_and_repeated_worker_is_idempotent(tmp_path):
    history, state = tmp_path / "history", tmp_path / "state"
    with HistoryArchive(history, Limits(min_free_bytes=0)):
        pass
    now = int(time.time()) // 300 * 300 + 20
    first = run_once(history, state, now=now, min_free_bytes=0)
    second = run_once(history, state, now=now, min_free_bytes=0)
    assert first["artifact_id"] == second["artifact_id"]
    assert first["metrics"] == second["metrics"] and first["readiness"] == second["readiness"]
    assert first["readiness"]["status"] == "collecting" and first["forecasts"] == []
    assert len(list((state / "runs").iterdir())) == 1
    public = json.loads((state / "public" / "summary.json").read_text())
    assert public["incident_evaluation_available"] is False
    assert not public["is_observed_train_headway"]
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "public").stat().st_mode) == 0o755
    assert stat.S_IMODE((state / "public" / "summary.json").stat().st_mode) == 0o644


def test_corrupt_immutable_evaluation_is_rejected_without_replacement(tmp_path):
    store = FeatureStore(tmp_path / "features.sqlite3", min_free_bytes=0)
    directory = tmp_path / "runs"
    directory.mkdir()
    report = {"paired_rows": [], "fixture_only": True}
    try:
        ident = publish_evaluation(directory, report, store, 600)
        provenance = json.loads((directory / ident / "provenance.json").read_text())
        assert provenance["source_manifest"] == source_manifest()
        assert "worker/history_time.py" in provenance["source_manifest"]["files"]
        assert "worker/temporal_features.py" in provenance["source_manifest"]["files"]
        path = directory / ident / "evaluation.json"
        path.write_text("tampered")
        with pytest.raises(ValueError, match="integrity"):
            publish_evaluation(directory, report, store, 600)
        assert path.read_text() == "tampered"
    finally:
        store.close()


def test_overlapping_worker_refuses_without_overwriting_status(tmp_path):
    history, state = tmp_path / "history", tmp_path / "state"
    state.mkdir()
    with (state / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            run_once(history, state, min_free_bytes=0)
    assert not (state / "public" / "summary.json").exists()


def test_export_backfill_survives_raw_retention_without_modifying_source(tmp_path):
    history, state = tmp_path / "history", tmp_path / "state"
    now = int(time.time())
    end = now - now % 86400 - 300
    raw = payload(end)
    with HistoryArchive(history, Limits(min_free_bytes=0)) as archive:
        for feed in FEEDS:
            archive.record(
                feed=feed,
                observed=end - 10,
                status="ok",
                http_status=200,
                latency_ms=1,
                payload=raw,
                metadata=payload_metadata(raw, end - 10, 180),
            )
        exported = export_completed(history, now=now, min_free_bytes=0)
        archive.prune(now + 8 * 86400)
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 0
    source = history / "parquet" / exported[0]["day_utc"] / "observations.parquet"
    before = source.read_bytes()
    store = FeatureStore(state / "features.sqlite3", min_free_bytes=0)
    try:
        cutoff = (now + 8 * 86400) // 300 * 300
        first = ingest(store, history, cutoff, time.monotonic() + 30)
        second = ingest(store, history, cutoff, time.monotonic() + 30)
        assert len(first["new_export_days"]) == 1 and not second["new_export_days"]
        assert store.window_metadata()[0]["window_end"] == end
        assert store.group_keys(0) == [("A", "platform:N")]
        assert source.read_bytes() == before
    finally:
        store.close()
