"""Offline clock semantics, not assertions about past unrecorded receipts."""

import json
import threading
import time

import httpx

from google.transit import gtfs_realtime_pb2
from worker.history import HistoryArchive, HistoryCollector, Limits
from worker.history_time import poll_availability


def test_new_collection_marks_completion_without_rewriting_legacy_rows(tmp_path, monkeypatch):
    start = int(time.time())
    clock = {"now": start}
    stop = threading.Event()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = start
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        archive.record(feed="ACE", observed=start - 20, status="network_error", http_status=None, latency_ms=5000)
        before = dict(archive.db.execute("SELECT * FROM polls WHERE id=1").fetchone())

        def response(request):
            clock["now"] += 4
            stop.set()
            return httpx.Response(200, content=feed.SerializeToString())

        monkeypatch.setattr("worker.history.time.time", lambda: clock["now"])
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            HistoryCollector(archive).collect(client, stop=stop)
        legacy = dict(archive.db.execute("SELECT * FROM polls WHERE id=1").fetchone())
        current = dict(archive.db.execute("SELECT * FROM polls WHERE id=2").fetchone())
        assert legacy == before
        assert current["observed_ts"] == start + 4
        details = json.loads(current["metadata_json"])
        assert details["poll_started_ts"] == start
        assert details["timestamp_semantics"] == "response_available_v2"
        assert details["age_seconds"] == 4
        assert poll_availability(current)[0] == start + 5
