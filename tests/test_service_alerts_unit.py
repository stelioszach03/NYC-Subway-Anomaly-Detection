import gzip
import json
import sqlite3

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs

from worker.service_alerts import Archive, active_interval, decode, publish, run_once

NOW = 1_900_000_000


def feed(now=NOW, text="Delays on the A line", future=False):
    f = gtfs.FeedMessage()
    f.header.gtfs_realtime_version = "2.0"
    f.header.timestamp = now
    e = f.entity.add()
    e.id = "lmm:alert:42:1"
    e.alert.header_text.translation.add(text=text, language="en")
    e.alert.header_text.translation.add(text="<script>bad()</script>", language="en-html")
    e.alert.description_text.translation.add(text="Official message", language="en")
    e.alert.informed_entity.add(route_id="A")
    e.alert.informed_entity.add(route_id="A")
    p = e.alert.active_period.add()
    p.start = now + 100 if future else now - 10
    p.end = now + 600
    return f


def client(payload=None, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, content=payload or b"")))


def test_plain_text_routes_and_current_period_are_preserved():
    source, items = decode(feed().SerializeToString(), NOW)
    assert source == NOW
    assert items[0]["routes"] == ["A"]
    assert items[0]["header"] == "Delays on the A line"
    assert "script" not in items[0]["header"]
    assert active_interval(items[0]["active_periods"], NOW) is not None
    assert active_interval(items[0]["active_periods"], NOW + 600) is None


def test_snapshot_provenance_revision_deduplication_and_receipt_clock(tmp_path):
    payload = feed().SerializeToString()
    with client(payload) as c:
        first = run_once(tmp_path, client=c, now_fn=lambda: NOW + 2)
        second = run_once(tmp_path, client=c, now_fn=lambda: NOW + 4)
    assert first["status"] == "ok" and second["archive"]["retained_polls"] == 2
    assert second["archive"]["retained_revisions"] == 1
    assert second["generated_ts"] == NOW + 4
    with sqlite3.connect(tmp_path / "alerts.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert gzip.decompress(db.execute("SELECT payload FROM snapshots").fetchone()[0]) == payload
        assert db.execute("SELECT first_seen,last_seen FROM revisions").fetchone() == (NOW + 2, NOW + 4)
    changed = feed(text="A service has resumed").SerializeToString()
    with client(changed) as c:
        result = run_once(tmp_path, client=c, now_fn=lambda: NOW + 5)
    assert result["archive"]["retained_revisions"] == 2
    assert not result["is_incident_ground_truth"] and not result["is_model_prediction"]
    assert (tmp_path / "public").stat().st_mode & 0o777 == 0o755
    assert (tmp_path / "public/summary.json").stat().st_mode & 0o777 == 0o644


def test_future_work_is_archived_but_not_shown_as_active(tmp_path):
    f = feed(future=True)
    f.entity[0].id = "lmm:planned_work:42"
    with client(f.SerializeToString()) as c:
        value = run_once(tmp_path, client=c, now_fn=lambda: NOW)
    assert value["total_feed_alerts"] == 1 and value["active_alert_count"] == 0
    assert value["alerts"] == [] and value["archive"]["retained_revisions"] == 1


@pytest.mark.parametrize("offset", [-601, 31])
def test_stale_or_future_source_is_not_current(tmp_path, offset):
    with client(feed(now=NOW + offset).SerializeToString()) as c:
        value = run_once(tmp_path, client=c, now_fn=lambda: NOW)
    assert value["status"] == "stale" and value["alerts"] == []


@pytest.mark.parametrize("payload,status", [(b"bad", 200), (b"", 503), (b"x" * (4 * 1024**2 + 1), 200)])
def test_fetch_or_parse_failure_clears_previous_public_alerts(tmp_path, payload, status):
    with client(feed().SerializeToString()) as c:
        assert run_once(tmp_path, client=c, now_fn=lambda: NOW)["alerts"]
    with client(payload, status) as c:
        value = run_once(tmp_path, client=c, now_fn=lambda: NOW + 1)
    assert value["status"] == "unavailable" and value["alerts"] == []
    assert "exception" not in json.dumps(value) and str(tmp_path) not in json.dumps(value)
    assert value["archive"]["retained_polls"] == 2


def test_incremental_duplicate_and_invalid_period_rejected():
    f = feed()
    f.header.incrementality = gtfs.FeedHeader.DIFFERENTIAL
    with pytest.raises(ValueError):
        decode(f.SerializeToString(), NOW)
    f = feed()
    f.entity.add().CopyFrom(f.entity[0])
    with pytest.raises(ValueError):
        decode(f.SerializeToString(), NOW)
    f = feed()
    f.entity[0].alert.active_period[0].end = NOW - 20
    with pytest.raises(ValueError):
        decode(f.SerializeToString(), NOW)


def test_retention_prunes_only_old_records_and_keeps_latest(tmp_path):
    archive = Archive(tmp_path)
    try:
        payload = feed().SerializeToString()
        ts, alerts = decode(payload, NOW)
        archive.record(payload, ts, alerts, NOW - 40 * 86400, "ok")
        archive.prune(NOW)
        assert archive.stats()["retained_polls"] == 0
        assert archive.stats()["retained_revisions"] == 0
        archive.record(payload, ts, alerts, NOW, "ok")
        archive.prune(NOW)
        assert archive.stats()["retained_polls"] == 1
        assert archive.stats()["database_bytes"] <= archive.stats()["max_database_bytes"]
    finally:
        archive.close()


def test_public_payload_byte_cap_marks_truncation_without_losing_archive(tmp_path):
    value = {
        "alerts": [{"description": "\u4e2d" * 1200} for _ in range(100)],
        "active_alert_count": 100,
        "display_truncated": False,
    }
    publish(tmp_path, value)
    data = (tmp_path / "public/summary.json").read_bytes()
    assert len(data) <= 256 * 1024
    stored = json.loads(data)
    assert stored["display_truncated"] and len(stored["alerts"]) < 100
    assert stored["active_alert_count"] == 100
