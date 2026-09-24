"""Synthetic fixtures only: no MTA requests or claims of forecasting quality."""

import gzip
import hashlib
import json
import time

import pytest

pytest.importorskip("pyarrow")

# These tests run in the dedicated optional history/export dependency job.
# ruff: noqa: E402
from google.transit import gtfs_realtime_pb2

from worker.history import FEEDS, HistoryArchive, Limits, payload_metadata
from worker.history_time import poll_availability
from worker.history_export import export_completed
from worker.temporal_features import (
    FeatureStore,
    WindowBuilder,
    decode_payload,
    parquet_windows,
    platform_direction,
    raw_windows,
)


def polls(end):
    return [
        {
            "id": i,
            "feed": feed,
            "observed_ts": end - 10,
            "source_ts": end - 12,
            "status": "ok",
            "http_status": 200,
            "freshness": "fresh",
            "sha256": str(i),
            "latency_ms": 1,
        }
        for i, feed in enumerate(FEEDS, 1)
    ]


def stop_row(trip, arrival, stop="A01N", **extra):
    return {
        "record_type": "trip_stop_update",
        "poll_id": 1,
        "route_id": "A",
        "stop_id": stop,
        "trip_id": trip,
        "start_date": "20260924",
        "arrival_ts": arrival,
        **extra,
    }


def test_distinct_trip_future_spacing_and_direction_are_not_observed_passages():
    builder = WindowBuilder(600, polls(600))
    for row in [
        stop_row("T1", 700),
        stop_row("T1", 710),
        stop_row("T2", 1000),
        stop_row("past", 590),
        stop_row("far", 5000),
        stop_row("skip", 750, stop_schedule_relationship=1),
        stop_row("S1", 800, "A01S"),
        stop_row("S2", 1100, "A01S"),
    ]:
        builder.add(row)
    result = builder.finish()
    assert result["complete_fresh_feed_coverage"]
    assert {row["direction"] for row in result["groups"]} == {"platform:N", "platform:S"}
    assert all(list(row["platform_spacing_seconds"].values()) == [300] for row in result["groups"])
    assert result["exclusions"]["missing_past_or_distant_arrival_prediction"] == 2
    assert platform_direction("opaque", None) == "unknown"
    assert platform_direction("opaque", 1) == "gtfs:1"


def test_missing_dates_or_unfresh_polls_are_not_replaced_with_guesses():
    records = polls(600)
    records[0]["source_ts"] = 0
    builder = WindowBuilder(600, records)
    builder.add(stop_row("T1", 800))
    builder.add(stop_row("T2", 1000))
    result = builder.finish()
    assert not result["complete_fresh_feed_coverage"] and not result["groups"]
    builder = WindowBuilder(600, polls(600))
    builder.add(stop_row("T1", 800, start_date=None))
    assert builder.finish()["exclusions"]["missing_trip_route_platform_or_service_date"] == 1


def payload(end):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = end - 10
    for index, arrival in enumerate((end + 100, end + 400)):
        item = feed.entity.add()
        item.id = f"entity-{index}"
        trip = item.trip_update.trip
        trip.trip_id = f"trip-{index}"
        trip.route_id = "A"
        trip.start_date = "20260923"
        stop = item.trip_update.stop_time_update.add()
        stop.stop_id = "A01N"
        stop.arrival.time = arrival
    return feed.SerializeToString()


def test_raw_and_immutable_parquet_extract_identical_completed_windows(tmp_path):
    now = int(time.time())
    end = now - now % 86400 - 300
    raw = payload(end)
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        for feed in FEEDS:
            for observed in (end - 20, end - 10):
                archive.record(
                    feed=feed,
                    observed=observed,
                    status="ok",
                    http_status=200,
                    latency_ms=1,
                    payload=raw,
                    metadata=payload_metadata(raw, observed, 180),
                )
    expected = list(raw_windows(tmp_path / "history.sqlite3", end - 300, end))
    exported = export_completed(tmp_path, now=now, min_free_bytes=0)
    actual = list(parquet_windows(tmp_path / "parquet" / exported[0]["day_utc"]))
    assert actual == expected
    assert len(actual) == 1 and actual[0]["selected_poll_count"] == 8
    assert len(actual[0]["groups"]) == 1


def test_raw_hash_and_incomplete_window_bounds_are_enforced(tmp_path):
    blob = gzip.compress(b"fixture")
    assert decode_payload(blob, hashlib.sha256(b"fixture").hexdigest()) == b"fixture"
    with pytest.raises(ValueError, match="hash"):
        decode_payload(blob, "wrong")
    with pytest.raises(ValueError, match="aligned"):
        list(raw_windows(tmp_path / "none.db", 0, 599))


def test_feature_transaction_idempotence_and_retention_never_touch_raw(tmp_path):
    store = FeatureStore(tmp_path / "features.sqlite3", min_free_bytes=0)
    window = WindowBuilder(600, polls(600)).finish()
    try:
        assert store.record(window)
        assert not store.record(window)
        tampered = json.loads(json.dumps(window))
        tampered["input_sha256"] = "changed"
        with pytest.raises(ValueError, match="refusing to rewrite"):
            store.record(tampered)
        store.prune(601)
        assert store.window_metadata() == []
    finally:
        store.close()


def test_legacy_request_crossing_window_end_cannot_be_used_before_response(tmp_path):
    now = int(time.time()) // 300 * 300
    raw = payload(now)
    with HistoryArchive(tmp_path, Limits(min_free_bytes=0)) as archive:
        for observed, latency in ((now - 20, 1), (now - 1, 2500)):
            archive.record(
                feed="ACE",
                observed=observed,
                status="ok",
                http_status=200,
                latency_ms=latency,
                payload=raw,
                metadata=payload_metadata(raw, observed, 180),
            )
    windows = list(raw_windows(tmp_path / "history.sqlite3", now - 300, now))
    assert len(windows) == 1
    assert windows[0]["source_polls"][0]["observed_ts"] == now - 20
    assert windows[0]["source_polls"][0]["available_ts"] <= now
    assert poll_availability({"observed_ts": 599, "latency_ms": 2500})[0] == 604
    assert (
        poll_availability(
            {"observed_ts": 599, "metadata_json": json.dumps({"timestamp_semantics": "response_available_v2"})}
        )[0]
        == 600
    )
    assert poll_availability({"observed_ts": 599}) == (None, "unknown")
