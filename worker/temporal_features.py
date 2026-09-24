"""Bounded retrospective features from raw/Parquet GTFS-RT, without network IO.

The stored target is a future feed-predicted arrival-spacing proxy, never an
observed train passage. Platform values remain separate until a train-only
stable cohort is chosen by the evaluator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import time

from worker.history import FEEDS
from worker.history_export import file_sha, normalized_rows
from worker.history_time import poll_availability

BIN_SECONDS = 300
FEATURE_SCHEMA = "mta-arrival-spacing-features-v2-availability"
DIRECTION_RULE = "nyct-platform-N-S-suffix-v1; otherwise explicit GTFS direction; otherwise unknown"
MAX_PAYLOAD_BYTES = 4 * 1024**2


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def platform_direction(stop_id, direction_id):
    if stop_id and stop_id[-1:] in ("N", "S"):
        return "platform:" + stop_id[-1:]
    if direction_id in (0, 1):
        return "gtfs:" + str(direction_id)
    return "unknown"


def compact_poll(row):
    available, semantics = poll_availability(row)
    return {
        "id": row.get("id", row.get("poll_id")),
        "observed_ts": row["observed_ts"],
        "feed": row["feed"],
        "status": row["status"],
        "http_status": row.get("http_status"),
        "source_ts": row.get("source_ts"),
        "freshness": row.get("freshness", row.get("freshness_at_receipt")),
        "sha256": row.get("sha256", row.get("snapshot_sha256")),
        "latency_ms": row.get("latency_ms", row.get("poll_latency_ms")),
        "available_ts": available,
        "availability_semantics": semantics,
    }


class WindowBuilder:
    def __init__(self, end, polls):
        self.end = end
        self.polls = {p["id"]: compact_poll(p) for p in polls}
        self.eligible = set()
        self.counts = Counter()
        self.stops = defaultdict(lambda: defaultdict(dict))
        for ident, poll in self.polls.items():
            if poll["feed"] not in FEEDS:
                raise ValueError("Unexpected source feed")
            if poll["available_ts"] is None or not end - BIN_SECONDS < poll["available_ts"] <= end:
                raise ValueError("Poll availability outside its completed feature window")
            source = poll["source_ts"]
            if (
                poll["status"] == "ok"
                and poll["freshness"] == "fresh"
                and source is not None
                and -60 <= end - source <= 180
            ):
                self.eligible.add(ident)
            else:
                self.counts["ineligible_poll"] += 1

    def add(self, row):
        if row.get("record_type") != "trip_stop_update" or row.get("poll_id") not in self.eligible:
            return
        self.counts["trip_stop_rows_seen"] += 1
        if (
            row.get("is_deleted")
            or row.get("schedule_relationship") not in (None, 0, 1, 2)
            or row.get("stop_schedule_relationship") not in (None, 0, 3)
        ):
            self.counts["excluded_schedule_relationship"] += 1
            return
        route, stop, trip, service_date = (row.get(key) for key in ("route_id", "stop_id", "trip_id", "start_date"))
        if not all(isinstance(v, str) and v for v in (route, stop, trip, service_date)):
            self.counts["missing_trip_route_platform_or_service_date"] += 1
            return
        arrival = row.get("arrival_ts")
        # Relative to decision availability, not producer timestamp: past ETAs
        # and future estimates beyond one hour are not treated as observations.
        if type(arrival) is not int or not self.end <= arrival <= self.end + 3600:
            self.counts["missing_past_or_distant_arrival_prediction"] += 1
            return
        group = (route, platform_direction(stop, row.get("direction_id")))
        identity = (trip, service_date, row.get("start_time") or "")
        previous = self.stops[group][stop].get(identity)
        self.stops[group][stop][identity] = arrival if previous is None else min(previous, arrival)

    def finish(self):
        feeds = {p["feed"] for p in self.polls.values()}
        fresh_feeds = {self.polls[ident]["feed"] for ident in self.eligible}
        groups = []
        for (route, direction), platforms in sorted(self.stops.items()):
            spacing = {}
            for stop, trips in platforms.items():
                times = sorted(trips.values())
                if len(times) >= 2:
                    spacing[stop] = times[1] - times[0]
            if spacing:
                groups.append(
                    {
                        "route_id": route,
                        "direction": direction,
                        "platform_spacing_seconds": spacing,
                        "platforms_with_arrival_predictions": len(platforms),
                        "platforms_with_two_distinct_trips": len(spacing),
                        "membership_sha256": hashlib.sha256(canonical(sorted(spacing))).hexdigest(),
                    }
                )
        source = sorted(self.polls.values(), key=lambda p: p["feed"])
        return {
            "window_end": self.end,
            "input_sha256": hashlib.sha256(canonical(source)).hexdigest(),
            "feeds_present": len(feeds),
            "fresh_feeds_at_decision": len(fresh_feeds),
            "complete_fresh_feed_coverage": fresh_feeds == set(FEEDS),
            "selected_poll_count": len(source),
            "source_polls": source,
            "exclusions": dict(self.counts),
            "availability_semantics_counts": dict(Counter(p["availability_semantics"] for p in source)),
            "groups": groups,
        }


def decode_payload(blob, expected_sha):
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
        payload = stream.read(MAX_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_PAYLOAD_BYTES or hashlib.sha256(payload).hexdigest() != expected_sha:
        raise ValueError("Raw snapshot failed bounded hash verification")
    return payload


def raw_windows(database, since, cutoff, *, deadline=None):
    """Latest poll per feed/5-minute window, including failed latest polls."""
    if since % BIN_SECONDS or cutoff % BIN_SECONDS or cutoff < since or cutoff - since > 86400:
        raise ValueError("Raw feature read must be aligned and bounded to at most one day")
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        selected = {}
        for record in db.execute(
            "SELECT * FROM polls WHERE observed_ts>=? AND observed_ts<=? ORDER BY id", (since - 86400, cutoff)
        ):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Temporal feature extraction deadline")
            poll = dict(record)
            available, _ = poll_availability(poll)
            if available is None or not since < available <= cutoff:
                continue
            end = ((available - 1) // BIN_SECONDS + 1) * BIN_SECONDS
            key = (end, poll["feed"])
            previous = selected.get(key)
            if previous is None or (available, poll["id"]) > (poll_availability(previous)[0], previous["id"]):
                selected[key] = poll
        grouped = defaultdict(list)
        for (end, _), poll in selected.items():
            grouped[end].append(poll)
        for end in sorted(grouped):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Temporal feature extraction deadline")
            pending = []
            for poll in grouped[end]:
                blob = db.execute("SELECT payload_gzip FROM snapshots WHERE sha256=?", (poll["sha256"],)).fetchone()
                pending.append({**poll, "payload_gzip": blob[0] if blob else None})
            yield build_raw_window(end, pending)


class LegacyAvailabilityUnavailable(ValueError):
    """An intact v1 export cannot establish historical input availability."""


def build_raw_window(end, polls):
    builder = WindowBuilder(end, polls)
    for poll in polls:
        blob = poll.get("payload_gzip")
        if poll["id"] in builder.eligible:
            if blob is None:
                raise ValueError("Fresh source poll has no retained payload")
            payload = decode_payload(blob, poll["sha256"])
            for row in normalized_rows(poll, payload):
                builder.add(row)
    return builder.finish()


def parquet_windows(day, *, deadline=None):
    """Two bounded streaming passes over an immutable completed-day export."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    manifest = json.loads((day / "manifest.json").read_text())
    path = day / "observations.parquet"
    parquet = pq.ParquetFile(path)
    if (
        manifest["schema_version"] not in (1, 2)
        or manifest["day_utc"] != day.name
        or file_sha(path) != manifest["sha256"]
        or parquet.metadata.num_rows != manifest["rows"]
    ):
        raise ValueError("Parquet source manifest/hash mismatch")
    if "available_ts" not in parquet.schema_arrow.names:
        raise LegacyAvailabilityUnavailable("Legacy Parquet has no input-availability timestamps; no times invented")
    columns = [
        "record_type",
        "poll_id",
        "observed_ts",
        "feed",
        "status",
        "http_status",
        "source_ts",
        "freshness_at_receipt",
        "snapshot_sha256",
        "poll_latency_ms",
        "available_ts",
        "availability_semantics",
    ]
    selected = {}
    day_start = int(datetime.strptime(day.name, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    for batch in parquet.iter_batches(batch_size=16384, columns=columns, use_threads=False):
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("Parquet feature extraction deadline")
        table = pa.Table.from_batches([batch])
        for row in table.filter(pc.equal(table["record_type"], "poll")).to_pylist():
            poll = compact_poll(row)
            if poll["available_ts"] is None:
                continue
            key = (((poll["available_ts"] - 1) // BIN_SECONDS + 1) * BIN_SECONDS, poll["feed"])
            # A legacy request can straddle UTC midnight. The first boundary
            # window needs adjacent-day context, so a standalone export never
            # invents completeness there; the raw-tail path can supply it.
            if not day_start + BIN_SECONDS < key[0] <= day_start + 86400:
                continue
            previous = selected.get(key)
            if previous is None or (poll["available_ts"], poll["id"]) > (previous["available_ts"], previous["id"]):
                selected[key] = poll
    grouped = defaultdict(list)
    for (end, _), poll in selected.items():
        grouped[end].append(poll)
    if not grouped:
        return
    ids = pa.array([poll["id"] for poll in selected.values()], type=pa.int64())
    columns += [
        "is_deleted",
        "trip_id",
        "route_id",
        "direction_id",
        "start_date",
        "start_time",
        "schedule_relationship",
        "stop_schedule_relationship",
        "stop_id",
        "arrival_ts",
    ]
    ends = sorted(grouped)
    next_end = 0
    builders = {}
    last_observed = None
    for batch in parquet.iter_batches(batch_size=8192, columns=columns, use_threads=False):
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("Parquet feature extraction deadline")
        table = pa.Table.from_batches([batch])
        selected_rows = table.filter(
            pc.and_(pc.is_in(table["poll_id"], value_set=ids), pc.equal(table["record_type"], "trip_stop_update"))
        ).to_pylist()
        for row in selected_rows:
            observed = row["observed_ts"]
            if last_observed is not None and observed < last_observed:
                raise ValueError("Parquet poll timestamps are not ordered")
            last_observed = observed
            # Availability can briefly reverse relative to old request-start
            # order. Flush only when later requests cannot enter a past window.
            while next_end < len(ends) and ends[next_end] <= observed:
                end = ends[next_end]
                yield builders.pop(end, WindowBuilder(end, grouped[end])).finish()
                next_end += 1
            end = ((row["available_ts"] - 1) // BIN_SECONDS + 1) * BIN_SECONDS
            if end < observed:
                raise ValueError("Input availability precedes its poll timestamp")
            if end not in builders:
                builders[end] = WindowBuilder(end, grouped[end])
            builders[end].add(row)
    for end in ends[next_end:]:
        yield builders.pop(end, WindowBuilder(end, grouped[end])).finish()


class FeatureStore:
    """Compact durable features; original archive/exports are never modified."""

    def __init__(self, path, *, max_bytes=512 * 1024**2, min_free_bytes=2 * 1024**3):
        self.path = Path(path)
        self.max_bytes, self.min_free_bytes = max_bytes, min_free_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.path.parent).free < min_free_bytes + 1024**2:
            raise OSError("Free-space reserve prevents temporal feature storage")
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS windows(
          window_end INTEGER PRIMARY KEY,input_sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS series(window_end INTEGER,route_id TEXT,direction TEXT,payload_gzip BLOB NOT NULL,
          PRIMARY KEY(route_id,direction,window_end));
          CREATE TABLE IF NOT EXISTS exports(day TEXT PRIMARY KEY,sha256 TEXT NOT NULL,state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);""")
        version = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        if version and version[0] != FEATURE_SCHEMA:
            self.db.close()
            raise ValueError("Incompatible temporal feature schema")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema',?)", (FEATURE_SCHEMA,))
        deriver = file_sha(Path(__file__))
        prior = self.db.execute("SELECT value FROM metadata WHERE key='deriver_sha256'").fetchone()
        if prior and prior[0] != deriver:
            self.db.close()
            raise ValueError("Feature derivation code changed; use a new versioned state directory")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('deriver_sha256',?)", (deriver,))

    def close(self):
        self.db.close()

    def record(self, window):
        derived_hash = hashlib.sha256(canonical(window["groups"])).hexdigest()
        existing = self.db.execute(
            "SELECT input_sha256,metadata_json FROM windows WHERE window_end=?", (window["window_end"],)
        ).fetchone()
        if existing:
            if existing[0] != window["input_sha256"] or json.loads(existing[1]).get("derived_sha256") != derived_hash:
                raise ValueError("Completed feature window changed; refusing to rewrite retained history")
            return False
        if (
            self.disk_bytes() > self.max_bytes
            or shutil.disk_usage(self.path.parent).free < self.min_free_bytes + 1024**2
        ):
            raise OSError("Temporal feature disk/free-space bound reached")
        metadata = {key: value for key, value in window.items() if key != "groups"}
        metadata["derived_sha256"] = derived_hash
        with self.db:
            self.db.execute(
                "INSERT INTO windows VALUES (?,?,?)",
                (window["window_end"], window["input_sha256"], canonical(metadata).decode()),
            )
            for row in window["groups"]:
                self.db.execute(
                    "INSERT INTO series VALUES (?,?,?,?)",
                    (window["window_end"], row["route_id"], row["direction"], gzip.compress(canonical(row), mtime=0)),
                )
        return True

    def disk_bytes(self):
        return sum(path.stat().st_size for path in self.path.parent.glob(self.path.name + "*") if path.is_file())

    def prune(self, cutoff):
        with self.db:
            self.db.execute("DELETE FROM series WHERE window_end<?", (cutoff,))
            self.db.execute("DELETE FROM windows WHERE window_end<?", (cutoff,))
        checkpoint = self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint[0] and self.disk_bytes() > self.max_bytes:
            raise OSError("A reader prevents temporal WAL reclamation")
        self.db.executescript("PRAGMA incremental_vacuum;")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        while self.disk_bytes() > self.max_bytes:
            oldest = [row[0] for row in self.db.execute("SELECT window_end FROM windows ORDER BY window_end LIMIT 128")]
            if not oldest:
                raise OSError("Temporal feature schema exceeds configured disk cap")
            with self.db:
                self.db.execute("DELETE FROM series WHERE window_end<=?", (oldest[-1],))
                self.db.execute("DELETE FROM windows WHERE window_end<=?", (oldest[-1],))
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.executescript("PRAGMA incremental_vacuum;")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def window_metadata(self, start=0):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT metadata_json FROM windows WHERE window_end>=? ORDER BY window_end", (start,)
            )
        ]

    def group_keys(self, start):
        return [
            tuple(row)
            for row in self.db.execute(
                "SELECT DISTINCT route_id,direction FROM series WHERE window_end>=? ORDER BY route_id,direction",
                (start,),
            )
        ]

    def group(self, route, direction, start):
        return {
            row[0]: json.loads(gzip.decompress(row[1]))
            for row in self.db.execute(
                "SELECT window_end,payload_gzip FROM series WHERE route_id=? AND direction=? AND window_end>=? ORDER BY window_end",
                (route, direction, start),
            )
        }

    def metadata(self, key, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_metadata(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, str(value)))
