"""Atomic daily Parquet export of completed UTC days from the raw archive.

Requires requirements.history-export.txt. No network calls or model inference.
Missing GTFS fields remain null; one poll row also preserves failure coverage.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2
from worker.history_time import poll_availability


SCHEMA_VERSION = 2
SCHEMA = pa.schema(
    [
        (name, dtype)
        for name, dtype in (
            ("record_type", pa.string()),
            ("poll_id", pa.int64()),
            ("observed_ts", pa.int64()),
            ("feed", pa.string()),
            ("status", pa.string()),
            ("http_status", pa.int32()),
            ("source_ts", pa.int64()),
            ("freshness_at_receipt", pa.string()),
            ("snapshot_sha256", pa.string()),
            ("poll_latency_ms", pa.float64()),
            ("available_ts", pa.int64()),
            ("availability_semantics", pa.string()),
            ("entity_id", pa.string()),
            ("is_deleted", pa.bool_()),
            ("trip_id", pa.string()),
            ("route_id", pa.string()),
            ("direction_id", pa.int32()),
            ("start_date", pa.string()),
            ("start_time", pa.string()),
            ("schedule_relationship", pa.int32()),
            ("stop_schedule_relationship", pa.int32()),
            ("trip_update_ts", pa.int64()),
            ("stop_id", pa.string()),
            ("stop_sequence", pa.int32()),
            ("arrival_ts", pa.int64()),
            ("departure_ts", pa.int64()),
            ("arrival_delay", pa.int32()),
            ("departure_delay", pa.int32()),
            ("vehicle_id", pa.string()),
            ("vehicle_ts", pa.int64()),
            ("latitude", pa.float64()),
            ("longitude", pa.float64()),
            ("bearing", pa.float64()),
            ("speed", pa.float64()),
            ("alert_json", pa.string()),
        )
    ],
    metadata={b"mta_history_schema": b"2", b"timestamp_unit": b"unix_seconds_utc"},
)


def optional(message, name):
    return getattr(message, name) if message.HasField(name) else None


def normalized_rows(poll: dict, payload: bytes | None):
    available, semantics = poll_availability(poll)
    base = {
        "poll_id": poll["id"],
        "observed_ts": poll["observed_ts"],
        "feed": poll["feed"],
        "status": poll["status"],
        "http_status": poll["http_status"],
        "source_ts": poll["source_ts"],
        "freshness_at_receipt": poll["freshness"],
        "snapshot_sha256": poll["sha256"],
        "poll_latency_ms": poll.get("latency_ms"),
        "available_ts": available,
        "availability_semantics": semantics,
    }
    yield {**base, "record_type": "poll"}
    if payload is None or poll["status"] != "ok":
        return
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    for entity in feed.entity:
        common = {**base, "entity_id": entity.id, "is_deleted": optional(entity, "is_deleted")}
        if entity.HasField("trip_update"):
            update = entity.trip_update
            trip = update.trip
            info = {
                name: optional(trip, name)
                for name in ("trip_id", "route_id", "direction_id", "start_date", "start_time", "schedule_relationship")
            }
            info["trip_update_ts"] = optional(update, "timestamp")
            vehicle_id = optional(update.vehicle, "id") if update.HasField("vehicle") else None
            if not update.stop_time_update:
                yield {**common, **info, "record_type": "trip_update", "vehicle_id": vehicle_id}
            for stop in update.stop_time_update:
                yield {
                    **common,
                    **info,
                    "record_type": "trip_stop_update",
                    "vehicle_id": vehicle_id,
                    "stop_id": optional(stop, "stop_id"),
                    "stop_sequence": optional(stop, "stop_sequence"),
                    "stop_schedule_relationship": optional(stop, "schedule_relationship"),
                    "arrival_ts": optional(stop.arrival, "time") if stop.HasField("arrival") else None,
                    "departure_ts": optional(stop.departure, "time") if stop.HasField("departure") else None,
                    "arrival_delay": optional(stop.arrival, "delay") if stop.HasField("arrival") else None,
                    "departure_delay": optional(stop.departure, "delay") if stop.HasField("departure") else None,
                }
        elif entity.HasField("vehicle"):
            vehicle = entity.vehicle
            info = {
                name: optional(vehicle.trip, name)
                for name in ("trip_id", "route_id", "direction_id", "start_date", "start_time", "schedule_relationship")
            }
            yield {
                **common,
                **info,
                "record_type": "vehicle",
                "vehicle_id": optional(vehicle.vehicle, "id"),
                "vehicle_ts": optional(vehicle, "timestamp"),
                "stop_id": optional(vehicle, "stop_id"),
                "stop_sequence": optional(vehicle, "current_stop_sequence"),
                **{
                    name: optional(vehicle.position, name) if vehicle.HasField("position") else None
                    for name in ("latitude", "longitude", "bearing", "speed")
                },
            }
        elif entity.HasField("alert"):
            yield {
                **common,
                "record_type": "alert",
                "alert_json": json.dumps(
                    MessageToDict(entity.alert, preserving_proto_field_name=True), separators=(",", ":")
                ),
            }
        else:
            yield {**common, "record_type": "entity"}


def file_sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def tree_bytes(directory: Path) -> int:
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file() and not p.is_symlink())


def enforce_exports(directory: Path, *, now: int, retention_days: int, max_bytes: int):
    days = sorted(
        p
        for p in directory.iterdir()
        if p.is_dir() and not p.is_symlink() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
    )
    cutoff = now - retention_days * 86400
    for day in list(days):
        stamp = datetime.strptime(day.name, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        if stamp + 86400 <= cutoff:
            shutil.rmtree(day)
            days.remove(day)
    while tree_bytes(directory) > max_bytes:
        if not days:
            raise OSError("Parquet archive cap reached before daily export completed")
        shutil.rmtree(days.pop(0))


def export_day(
    db: sqlite3.Connection,
    directory: Path,
    day: str,
    *,
    now: int,
    max_bytes: int,
    min_free_bytes: int,
    retention_days: int,
) -> dict:
    start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    if start + 86400 > now - now % 86400:
        raise ValueError("Only completed UTC days may be exported")
    target = directory / day
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text())
        if (
            file_sha(target / "observations.parquet") != manifest["sha256"]
            or manifest["schema_version"] not in (1, SCHEMA_VERSION)
            or manifest["day_utc"] != day
            or pq.read_metadata(target / "observations.parquet").num_rows != manifest["rows"]
        ):
            raise ValueError("Existing immutable export failed hash verification")
        return manifest
    stage = directory / (".stage-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    parquet_path = stage / "observations.parquet"
    counts = Counter()
    statuses = Counter()
    poll_count = 0
    first_poll = last_poll = None
    writer = None
    try:
        if shutil.disk_usage(directory).free < min_free_bytes + 16 * 1024**2:
            raise OSError("Free-space reserve prevents Parquet export")
        writer = pq.ParquetWriter(parquet_path, SCHEMA, compression="zstd", use_dictionary=True)
        rows = []

        def flush():
            if rows:
                if shutil.disk_usage(directory).free < min_free_bytes + 16 * 1024**2:
                    raise OSError("Free-space reserve prevents Parquet batch write")
                writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
                rows.clear()
                enforce_exports(directory, now=now, retention_days=retention_days, max_bytes=max_bytes)

        cursor = db.execute(
            """SELECT p.*, s.payload_gzip FROM polls p
            LEFT JOIN snapshots s ON s.sha256=p.sha256
            WHERE p.observed_ts>=? AND p.observed_ts<? ORDER BY p.observed_ts,p.id""",
            (start, start + 86400),
        )
        try:
            for record in cursor:
                poll = dict(record)
                blob = poll.pop("payload_gzip")
                payload = gzip.decompress(blob) if blob is not None else None
                if payload is not None and hashlib.sha256(payload).hexdigest() != poll["sha256"]:
                    raise ValueError("Raw snapshot failed hash verification")
                poll_count += 1
                first_poll = poll["observed_ts"] if first_poll is None else first_poll
                last_poll = poll["observed_ts"]
                statuses[poll["status"]] += 1
                for row in normalized_rows(poll, payload):
                    counts[row["record_type"]] += 1
                    rows.append(row)
                    if len(rows) >= 4096:
                        flush()
            flush()
        finally:
            cursor.close()
        writer.close()
        writer = None
        measured = pq.read_metadata(parquet_path).num_rows
        if measured != sum(counts.values()):
            raise ValueError("Parquet row count validation failed")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "day_utc": day,
            "generated_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "sha256": file_sha(parquet_path),
            "bytes": parquet_path.stat().st_size,
            "rows": measured,
            "polls": poll_count,
            "row_types": dict(counts),
            "poll_statuses": dict(statuses),
            "first_poll_ts": first_poll,
            "last_poll_ts": last_poll,
            "extractor_sha256": file_sha(Path(__file__)),
            "pyarrow_version": pa.__version__,
            "limitations": "Feed predictions and optional fields; no inferred passage, incident labels or guaranteed daily coverage.",
        }
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        for path in (parquet_path, manifest_path):
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        enforce_exports(directory, now=now, retention_days=retention_days, max_bytes=max_bytes)
        stage.rename(target)
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return manifest
    except BaseException:
        if writer is not None:
            writer.close()
        shutil.rmtree(stage, ignore_errors=True)
        raise


def export_completed(
    directory: Path,
    *,
    now: int | None = None,
    retention_days: int = 90,
    max_bytes: int = 10 * 1024**3,
    min_free_bytes: int = 2 * 1024**3,
) -> list[dict]:
    if retention_days < 1 or max_bytes < 128 * 1024 or min_free_bytes < 0:
        raise ValueError("Invalid export retention, cap or free-space reserve")
    now = int(time.time()) if now is None else now
    output = directory / "parquet"
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "export.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for stale in output.glob(".stage-*"):
            if stale.is_dir() and not stale.is_symlink():
                shutil.rmtree(stale)
        enforce_exports(output, now=now, retention_days=retention_days, max_bytes=max_bytes)
        with closing(sqlite3.connect((directory / "history.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            days = [
                r[0]
                for r in db.execute(
                    """SELECT DISTINCT strftime('%Y-%m-%d', observed_ts, 'unixepoch')
                FROM polls WHERE observed_ts<? AND observed_ts>=? ORDER BY 1""",
                    (now - now % 86400, now - retention_days * 86400),
                )
            ]
            return [
                export_day(
                    db,
                    output,
                    day,
                    now=now,
                    max_bytes=max_bytes,
                    min_free_bytes=min_free_bytes,
                    retention_days=retention_days,
                )
                for day in days
            ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "var/history")))
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--max-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--min-free-bytes", type=int, default=2 * 1024**3)
    args = parser.parse_args()
    print(
        json.dumps(
            export_completed(
                args.state_dir,
                retention_days=args.retention_days,
                max_bytes=args.max_bytes,
                min_free_bytes=args.min_free_bytes,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
