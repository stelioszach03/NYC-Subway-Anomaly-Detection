"""Optional PyArrow export coverage; base history tests need no PyArrow."""
import gzip
import hashlib
import json
import time
from datetime import datetime, timezone

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402
from google.transit import gtfs_realtime_pb2  # noqa: E402

from worker.history import HistoryArchive, Limits, payload_metadata  # noqa: E402
from worker.history_export import enforce_exports, export_completed, normalized_rows  # noqa: E402


def example(stamp):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = stamp - 600
    entity = feed.entity.add()
    entity.id = "trip-1"
    entity.trip_update.trip.trip_id = "T1"
    entity.trip_update.trip.route_id = "A"
    stop = entity.trip_update.stop_time_update.add()
    stop.stop_id = "A01N"
    stop.arrival.time = stamp + 120
    stop.schedule_relationship = 1
    vehicle = feed.entity.add()
    vehicle.id = "vehicle-1"
    vehicle.vehicle.vehicle.id = "V1"
    vehicle.vehicle.timestamp = stamp - 5
    vehicle.vehicle.position.latitude = 40.7
    vehicle.vehicle.position.longitude = -73.9
    alert = feed.entity.add()
    alert.id = "alert-1"
    alert.alert.header_text.translation.add(text="Test-only alert", language="en")
    return feed.SerializeToString()


def prepare(directory):
    now = int(time.time())
    stamp = now - now % 86400 - 120
    with HistoryArchive(directory, Limits(min_free_bytes=0)) as archive:
        payload = example(stamp)
        archive.record(feed="ACE", observed=stamp, status="ok", http_status=200, latency_ms=1,
                       payload=payload, metadata=payload_metadata(payload, stamp, 180))
        archive.record(feed="G", observed=stamp, status="http_error", http_status=503, latency_ms=2)
        archive.record(feed="L", observed=now, status="ok", http_status=200, latency_ms=1,
                       payload=example(now), metadata=payload_metadata(example(now), now, 180))
    return now, stamp


def test_completed_day_export_typed_nulls_counts_and_hash(tmp_path):
    now, stamp = prepare(tmp_path)
    manifests = export_completed(tmp_path, now=now, min_free_bytes=0)
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest["polls"] == 2
    assert manifest["rows"] == 5  # two polls + one trip stop, vehicle and alert
    assert manifest["poll_statuses"] == {"ok": 1, "http_error": 1}
    path = tmp_path / "parquet" / manifest["day_utc"] / "observations.parquet"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"]
    rows = pq.read_table(path).to_pylist()
    trip = next(r for r in rows if r["record_type"] == "trip_stop_update")
    assert trip["direction_id"] is None
    assert trip["departure_ts"] is None
    assert trip["arrival_ts"] == stamp + 120
    assert trip["stop_schedule_relationship"] == 1
    assert trip["freshness_at_receipt"] == "stale"
    assert trip["source_ts"] == stamp - 600
    vehicle = next(r for r in rows if r["record_type"] == "vehicle")
    assert vehicle["latitude"] == pytest.approx(40.7)
    assert vehicle["arrival_ts"] is None
    alert = next(r for r in rows if r["record_type"] == "alert")
    assert "Test-only alert" in alert["alert_json"]
    assert not list((tmp_path / "parquet").glob(".stage-*"))


def test_export_restart_is_idempotent_and_keeps_raw(tmp_path):
    now, _ = prepare(tmp_path)
    first = export_completed(tmp_path, now=now, min_free_bytes=0)
    second = export_completed(tmp_path, now=now + 1, min_free_bytes=0)
    assert first == second
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 3


def test_corrupt_export_is_rejected_not_silently_replaced(tmp_path):
    now, _ = prepare(tmp_path)
    result = export_completed(tmp_path, now=now, min_free_bytes=0)
    path = tmp_path / "parquet" / result[0]["day_utc"] / "observations.parquet"
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="hash verification"):
        export_completed(tmp_path, now=now, min_free_bytes=0)
    assert path.read_bytes() == b"invalid"


def test_failed_write_has_no_published_partial_and_preserves_raw(tmp_path, monkeypatch):
    now, _ = prepare(tmp_path)
    monkeypatch.setattr("worker.history_export.pa.Table", None)
    with pytest.raises(AttributeError):
        export_completed(tmp_path, now=now, min_free_bytes=0)
    assert list((tmp_path / "parquet").iterdir()) == []
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 3


def test_free_space_refusal_publishes_nothing(tmp_path):
    now, _ = prepare(tmp_path)
    with pytest.raises(OSError, match="Free-space reserve"):
        export_completed(tmp_path, now=now, min_free_bytes=10**20)
    assert list((tmp_path / "parquet").iterdir()) == []


def test_retention_removes_old_completed_days_but_not_active_archive(tmp_path):
    now, _ = prepare(tmp_path)
    first = export_completed(tmp_path, now=now, min_free_bytes=0)
    path = tmp_path / "parquet" / first[0]["day_utc"]
    assert path.exists()
    assert export_completed(tmp_path, now=now + 100 * 86400, min_free_bytes=0) == []
    assert not path.exists()
    assert (tmp_path / "history.sqlite3").exists()


def test_corrupt_raw_snapshot_blocks_publication(tmp_path):
    now, _ = prepare(tmp_path)
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        with archive.db:
            archive.db.execute("UPDATE snapshots SET payload_gzip=?", (gzip.compress(b"corrupt"),))
    with pytest.raises(ValueError, match="Raw snapshot failed hash"):
        export_completed(tmp_path, now=now, min_free_bytes=0)
    assert list((tmp_path / "parquet").iterdir()) == []


def test_decode_error_preserves_poll_but_does_not_invent_entity():
    poll = {"id": 1, "observed_ts": 1000, "feed": "G", "status": "decode_error",
            "http_status": 200, "source_ts": None, "freshness": "unknown", "sha256": "abc"}
    rows = list(normalized_rows(poll, b"invalid"))
    assert len(rows) == 1
    assert rows[0]["record_type"] == "poll"
    assert rows[0]["source_ts"] is None


def test_manifest_row_tampering_rejected(tmp_path):
    now, _ = prepare(tmp_path)
    result = export_completed(tmp_path, now=now, min_free_bytes=0)
    path = tmp_path / "parquet" / result[0]["day_utc"] / "manifest.json"
    value = json.loads(path.read_text())
    value["rows"] = 999
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="hash verification"):
        export_completed(tmp_path, now=now, min_free_bytes=0)


def test_manifest_source_day_is_utc(tmp_path):
    now, stamp = prepare(tmp_path)
    result = export_completed(tmp_path, now=now, min_free_bytes=0)
    assert result[0]["day_utc"] == datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")


def test_export_disk_cap_evicts_oldest_completed_day_first(tmp_path):
    first, second = tmp_path / "2026-09-20", tmp_path / "2026-09-21"
    first.mkdir()
    second.mkdir()
    (first / "observations.parquet").write_bytes(b"a" * 100_000)
    (second / "observations.parquet").write_bytes(b"b" * 100_000)
    now = int(datetime(2026, 9, 23, tzinfo=timezone.utc).timestamp())
    enforce_exports(tmp_path, now=now, retention_days=90, max_bytes=150_000)
    assert not first.exists()
    assert second.exists()


def test_current_staging_larger_than_cap_fails_without_publishing(tmp_path):
    stage = tmp_path / ".stage-test"
    stage.mkdir()
    (stage / "observations.parquet").write_bytes(b"a" * 150_000)
    with pytest.raises(OSError, match="cap reached"):
        enforce_exports(tmp_path, now=int(time.time()), retention_days=90, max_bytes=128 * 1024)
    assert stage.exists()
