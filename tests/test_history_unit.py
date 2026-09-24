"""Offline archival contract tests: no MTA request, scoring, or production DB."""
import gzip
import hashlib
import os
import time
from collections import namedtuple

import httpx
import pytest
from google.transit import gtfs_realtime_pb2

from worker.history import FEEDS, HistoryArchive, HistoryCollector, Limits, archive_status, payload_metadata, retry_delay


def feed_bytes(stamp=None):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    if stamp is not None:
        feed.header.timestamp = stamp
    entity = feed.entity.add()
    entity.id = "trip-record"
    trip = entity.trip_update.trip
    trip.trip_id = "a-trip"
    trip.route_id = "A"
    trip.direction_id = 1
    trip.start_date = "20260923"
    update = entity.trip_update.stop_time_update.add()
    update.stop_id = "A01N"
    update.arrival.time = (stamp or 1000) + 90
    return feed.SerializeToString()


def limits(**kwargs):
    return Limits(**{"min_free_bytes": 0, "max_bytes": 8 * 1024**2, **kwargs})


@pytest.mark.parametrize("source,expected", [(None, "unknown"), (1000, "fresh"), (500, "stale"), (1200, "future")])
def test_source_freshness_is_not_fetch_success(source, expected):
    value = payload_metadata(feed_bytes(source), 1000, 180)
    assert value["freshness"] == expected
    assert value["source_ts"] == source
    assert value["trip_updates"] == 1
    assert value["vehicle_positions"] == 0


def test_atomic_raw_snapshot_preserves_trip_and_unknown_extension_bytes(tmp_path):
    now = int(time.time())
    # Unknown protobuf field 99 (varint=1) survives because bytes are not re-serialized.
    payload = feed_bytes(now) + b"\x98\x06\x01"
    with HistoryArchive(tmp_path, limits()) as archive:
        metadata = payload_metadata(payload, now, 180)
        for _ in range(2):
            archive.record(feed="ACE", observed=now, status="ok", http_status=200,
                           latency_ms=10, payload=payload, metadata=metadata)
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 2
        row = archive.db.execute("SELECT * FROM snapshots").fetchone()
        assert gzip.decompress(row["payload_gzip"]) == payload
        assert row["sha256"] == hashlib.sha256(payload).hexdigest()
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
    with HistoryArchive(tmp_path, limits()) as archive:
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 2
        assert archive.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_archive_is_single_writer(tmp_path):
    with HistoryArchive(tmp_path, limits()):
        with pytest.raises(RuntimeError, match="Another historical collector"):
            HistoryArchive(tmp_path, limits())


def test_retention_removes_only_unreferenced_snapshots(tmp_path):
    now = int(time.time())
    with HistoryArchive(tmp_path, limits(retention_seconds=100)) as archive:
        for observed in (now - 101, now):
            archive.record(feed="ACE", observed=observed, status="ok", http_status=200,
                           latency_ms=1, payload=feed_bytes(now))
        archive.prune(now)
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 1
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        archive.prune(now + 101)
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 0
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_row_cap_preserves_newest_polls(tmp_path):
    now = int(time.time())
    with HistoryArchive(tmp_path, limits(max_polls=3)) as archive:
        for index in range(5):
            archive.record(feed="ACE", observed=now + index, status="ok", http_status=200, latency_ms=1)
        archive.prune(now)
        rows = archive.db.execute("SELECT observed_ts FROM polls ORDER BY id").fetchall()
        assert [r[0] for r in rows] == [now + 2, now + 3, now + 4]


def test_byte_cap_reclaims_sqlite_wal_and_pages(tmp_path):
    now = int(time.time())
    budget = 1024 * 1024
    with HistoryArchive(tmp_path, limits(max_bytes=budget)) as archive:
        for index in range(18):
            archive.record(feed="ACE", observed=now + index, status="decode_error", http_status=200,
                           latency_ms=1, payload=os.urandom(90_000))
        archive.prune(now)
        assert archive.disk_bytes() <= budget
        assert 0 < archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] < 18
        assert archive.db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2


def test_free_space_guard_does_not_commit_snapshot_or_poll(tmp_path, monkeypatch):
    with HistoryArchive(tmp_path, limits()) as archive:
        usage = namedtuple("usage", "total used free")(1_000_000, 999_999, 1)
        monkeypatch.setattr("worker.history.shutil.disk_usage", lambda _: usage)
        with pytest.raises(OSError, match="Free-space reserve"):
            archive.record(feed="ACE", observed=int(time.time()), status="ok", http_status=200,
                           latency_ms=1, payload=feed_bytes())
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 0
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_http_decode_and_oversize_failures_do_not_stop_other_feeds(tmp_path):
    now = int(time.time())
    payload = feed_bytes(now - 500)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "180"})
        if len(calls) == 2:
            return httpx.Response(200, content=b"invalid")
        if len(calls) == 3:
            return httpx.Response(200, content=b"x" * 1001)
        return httpx.Response(200, content=payload)

    with HistoryArchive(tmp_path, limits(max_response_bytes=1000)) as archive:
        collector = HistoryCollector(archive)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            collector.collect(client)
        rows = archive.db.execute("SELECT * FROM polls ORDER BY id").fetchall()
        assert len(rows) == len(FEEDS)
        assert [r["status"] for r in rows[:3]] == ["http_error", "decode_error", "response_too_large"]
        assert rows[1]["sha256"] is not None  # malformed body retained, not silently discarded
        assert rows[2]["sha256"] is None
        assert rows[-1]["freshness"] == "stale"
        assert collector.cooldowns["1234567"] > time.monotonic() + 170


def test_status_distinguishes_new_fetch_from_old_source_and_old_archive(tmp_path):
    now = int(time.time())
    with HistoryArchive(tmp_path, limits()) as archive:
        archive.record(feed="ACE", observed=now, status="ok", http_status=200, latency_ms=1,
                       payload=feed_bytes(now - 500), metadata=payload_metadata(feed_bytes(now - 500), now, 180))
        result = archive_status(tmp_path, now + 100)
        feed = next(r for r in result["feeds"] if r["feed"] == "ACE")
        assert feed["last_poll_age_seconds"] == 100
        assert feed["current_feed_age_seconds"] == 600
        assert feed["freshness"] == "stale"
        assert result["polls"] == result["snapshots"] == 1


def test_network_timeout_is_recorded_and_cycle_continues(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("unreachable", request=request)

    with HistoryArchive(tmp_path, limits()) as archive, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        HistoryCollector(archive).collect(client)
        assert archive.db.execute("SELECT COUNT(*) FROM polls WHERE status='network_error'").fetchone()[0] == len(FEEDS)
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_transaction_failure_rolls_back_snapshot(tmp_path):
    with HistoryArchive(tmp_path, limits()) as archive:
        archive.db.execute("CREATE TRIGGER reject_poll BEFORE INSERT ON polls BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
        with pytest.raises(Exception, match="test failure"):
            archive.record(feed="ACE", observed=int(time.time()), status="ok", http_status=200,
                           latency_ms=1, payload=feed_bytes())
        assert archive.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_retry_after_http_date_and_long_delay_are_not_shortened():
    assert retry_delay("7200", 0) == 7200
    assert retry_delay("Thu, 01 Jan 1970 02:00:00 GMT", 0) == 7200
    assert retry_delay("bad", 0) == 60
    assert retry_delay("-1", 0) == 60


def test_cooldown_prevents_request_for_affected_feed_only(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "7200"})

    with HistoryArchive(tmp_path, limits()) as archive, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = HistoryCollector(archive)
        collector.collect(client)
        assert len(calls) == 8
        collector.cooldowns["ACE"] = 0
        collector.collect(client)
        assert len(calls) == 9
        assert calls[-1] == FEEDS["ACE"]


def test_pinned_wal_fails_closed_instead_of_deleting_entire_archive(tmp_path, monkeypatch):
    now = int(time.time())
    with HistoryArchive(tmp_path, limits()) as archive:
        for index in range(3):
            archive.record(feed="ACE", observed=now + index, status="ok", http_status=200, latency_ms=1)
        monkeypatch.setattr(archive, "_compact", lambda: False)
        monkeypatch.setattr(archive, "disk_bytes", lambda: archive.limits.max_bytes + 1)
        with pytest.raises(OSError, match="reader prevents WAL"):
            archive.prune(now)
        assert archive.db.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 3
