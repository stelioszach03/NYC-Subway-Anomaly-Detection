"""Bounded, independent raw GTFS-RT history collector (no model or API server).

Original protobuf bytes are retained, including unknown MTA extension fields.
Feed estimates are not labelled as observed train arrivals or incident truth.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import logging
import os
import shutil
import signal
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from google.transit import gtfs_realtime_pb2


LOG = logging.getLogger("mta.history")
BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"
FEEDS = {name: BASE + suffix for name, suffix in (
    ("1234567", "gtfs"), ("ACE", "gtfs-ace"), ("BDFM", "gtfs-bdfm"),
    ("G", "gtfs-g"), ("JZ", "gtfs-jz"), ("NQRW", "gtfs-nqrw"),
    ("L", "gtfs-l"), ("SI", "gtfs-si"),
)}


@dataclass(frozen=True)
class Limits:
    retention_seconds: int = 7 * 86400
    max_bytes: int = 2 * 1024**3
    min_free_bytes: int = 2 * 1024**3
    max_polls: int = 150_000
    max_response_bytes: int = 4 * 1024**2
    stale_after_seconds: int = 180

    def __post_init__(self):
        if min(self.retention_seconds, self.max_polls, self.max_response_bytes, self.stale_after_seconds) <= 0:
            raise ValueError("Retention, row, response and freshness limits must be positive")
        if self.max_bytes < 128 * 1024 or self.min_free_bytes < 0:
            raise ValueError("Archive cap must be >=128KiB and free-space reserve nonnegative")


def payload_metadata(payload: bytes, observed: int, stale_after: int) -> dict:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    if not feed.IsInitialized():
        raise ValueError("Uninitialized GTFS-RT message")
    source = int(feed.header.timestamp) if feed.header.HasField("timestamp") else None
    age = observed - source if source is not None else None
    freshness = "unknown" if age is None else "future" if age < -60 else "stale" if age > stale_after else "fresh"
    return {
        "source_ts": source, "age_seconds": age, "freshness": freshness,
        "entities": len(feed.entity),
        "trip_updates": sum(e.HasField("trip_update") for e in feed.entity),
        "vehicle_positions": sum(e.HasField("vehicle") for e in feed.entity),
        "alerts": sum(e.HasField("alert") for e in feed.entity),
    }


def retry_delay(value: str | None, now: int) -> float:
    """Honor seconds or HTTP-date without retrying before a long server delay."""
    text = (value or "").strip()[:64]
    try:
        return float(max(60, int(text)))
    except ValueError:
        try:
            date = parsedate_to_datetime(text)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(60, date.timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 60.0


class HistoryArchive:
    """Single writer; each compressed snapshot + poll manifest commits atomically.

    Content-addressed payloads deduplicate identical responses, while every poll
    remains recorded. Caps include SQLite WAL/SHM. A failed disk guard logs and
    stops writes instead of borrowing disk reserved for the other VPS services.
    """

    def __init__(self, directory: Path, limits: Limits):
        self.directory = directory
        self.limits = limits
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "history.sqlite3"
        self.lock = (directory / "writer.lock").open("a")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("Another historical collector owns this archive") from None
        if shutil.disk_usage(directory).free < limits.min_free_bytes + 128 * 1024:
            self.lock.close()
            raise OSError("Free-space reserve prevents archive initialization")
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if self.db.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
            self.close()
            raise ValueError("Archive must support incremental vacuum; refusing an incompatible database")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.close()
            raise ValueError("Unsupported archive schema version")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                sha256 TEXT PRIMARY KEY, payload_gzip BLOB NOT NULL, raw_bytes INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY, observed_ts INTEGER NOT NULL, feed TEXT NOT NULL,
                http_status INTEGER, status TEXT NOT NULL, latency_ms REAL NOT NULL,
                sha256 TEXT REFERENCES snapshots(sha256), source_ts INTEGER,
                freshness TEXT NOT NULL, metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS polls_time ON polls(observed_ts);
            CREATE INDEX IF NOT EXISTS polls_feed_time ON polls(feed, observed_ts);
            CREATE INDEX IF NOT EXISTS polls_sha ON polls(sha256);
            PRAGMA user_version=1;
        """)
        self.prune(int(time.time()))

    def close(self):
        self.db.close()
        self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def disk_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.directory.glob("history.sqlite3*") if p.is_file())

    def _compact(self) -> bool:
        checkpoint = self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint[0]:
            return False  # A read snapshot pins WAL; deleting more cannot fix it.
        # executescript drains the pragma; execute alone only frees one page.
        self.db.executescript("PRAGMA incremental_vacuum;")
        return not self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]

    def _delete_orphans(self):
        self.db.execute("DELETE FROM snapshots WHERE NOT EXISTS (SELECT 1 FROM polls WHERE polls.sha256=snapshots.sha256)")

    def prune(self, now: int, headroom: int = 0):
        with self.db:
            self.db.execute("DELETE FROM polls WHERE observed_ts < ?", (now - self.limits.retention_seconds,))
            self.db.execute("DELETE FROM polls WHERE id NOT IN (SELECT id FROM polls ORDER BY id DESC LIMIT ?)", (self.limits.max_polls,))
            self._delete_orphans()
        compacted = self._compact()
        while self.disk_bytes() + headroom > self.limits.max_bytes:
            if not compacted:
                raise OSError("Archive cap reached while a reader prevents WAL reclamation")
            with self.db:
                deleted = self.db.execute("DELETE FROM polls WHERE id IN (SELECT id FROM polls ORDER BY id LIMIT 128)").rowcount
                self._delete_orphans()
            compacted = self._compact()
            if not deleted:
                raise OSError("Archive cap cannot accommodate this response")

    def record(self, *, feed: str, observed: int, status: str, http_status: int | None,
               latency_ms: float, payload: bytes | None = None, metadata: dict | None = None):
        if feed not in FEEDS:
            raise ValueError("Unknown feed")
        if payload is not None and len(payload) > self.limits.max_response_bytes:
            raise ValueError("Payload exceeds response cap")
        digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
        zipped = gzip.compress(payload, compresslevel=5, mtime=0) if payload is not None else None
        needed = 2 * len(zipped or b"") + 128 * 1024
        if self.disk_bytes() + needed > self.limits.max_bytes:
            self.prune(observed, headroom=needed)
        if shutil.disk_usage(self.directory).free < self.limits.min_free_bytes + needed:
            raise OSError("Free-space reserve prevents historical write")
        details = dict(metadata or {})
        with self.db:
            if digest is not None:
                self.db.execute("INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?)", (digest, zipped, len(payload)))
            self.db.execute("""INSERT INTO polls
                (observed_ts,feed,http_status,status,latency_ms,sha256,source_ts,freshness,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?)""", (
                observed, feed, http_status, status, latency_ms, digest,
                details.get("source_ts"), details.get("freshness", "unknown"),
                json.dumps(details, separators=(",", ":")),
            ))


def archive_status(directory: Path, now: int | None = None) -> dict:
    """Read-only local status; API callers need never obtain writer access."""
    now = int(time.time()) if now is None else now
    path = directory / "history.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        totals = dict(db.execute("SELECT COUNT(*) polls, MIN(observed_ts) first_poll, MAX(observed_ts) last_poll FROM polls").fetchone())
        totals["snapshots"] = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        feeds = []
        for feed in FEEDS:
            row = db.execute("SELECT observed_ts,source_ts,status,freshness,http_status FROM polls WHERE feed=? ORDER BY id DESC LIMIT 1", (feed,)).fetchone()
            item = dict(row) if row else {}
            item.update(feed=feed, last_poll_age_seconds=now - row["observed_ts"] if row else None,
                        current_feed_age_seconds=now - row["source_ts"] if row and row["source_ts"] is not None else None)
            feeds.append(item)
        return {"schema_version": 1, "archive_bytes": sum(p.stat().st_size for p in directory.glob("history.sqlite3*") if p.is_file()),
                "free_bytes": shutil.disk_usage(directory).free, **totals, "feeds": feeds}


class HistoryCollector:
    def __init__(self, archive: HistoryArchive):
        self.archive = archive
        self.cooldowns: dict[str, float] = {}

    def collect(self, client: httpx.Client, stop: threading.Event | None = None):
        for feed, url in FEEDS.items():
            if stop and stop.is_set():
                break
            if time.monotonic() < self.cooldowns.get(feed, 0):
                continue
            started = time.monotonic()
            observed = int(time.time())
            status, code, payload, details = "network_error", None, None, {}
            try:
                with client.stream("GET", url) as response:
                    code = response.status_code
                    if code == 200:
                        chunks, size = [], 0
                        for chunk in response.iter_bytes(chunk_size=65536):
                            if time.monotonic() - started > 20:
                                raise httpx.ReadTimeout("Feed response exceeded total read deadline")
                            size += len(chunk)
                            if size > self.archive.limits.max_response_bytes:
                                raise ValueError("response_too_large")
                            chunks.append(chunk)
                        payload = b"".join(chunks)
                        try:
                            details = payload_metadata(payload, observed, self.archive.limits.stale_after_seconds)
                            status = "ok"
                        except Exception:
                            status = "decode_error"
                    else:
                        status = "http_error"
                        # One request per due cycle; no retry storm on rate limiting.
                        if code in (429, 503):
                            delay = retry_delay(response.headers.get("Retry-After"), observed)
                            self.cooldowns[feed] = time.monotonic() + delay
                            details["retry_after_seconds"] = delay
            except ValueError as exc:
                status = "response_too_large" if str(exc) == "response_too_large" else "read_error"
            except httpx.HTTPError as exc:
                details["error_type"] = type(exc).__name__
            self.archive.record(feed=feed, observed=observed, status=status, http_status=code,
                                latency_ms=round((time.monotonic() - started) * 1000, 1),
                                payload=payload, metadata=details)
            LOG.info("feed=%s status=%s freshness=%s", feed, status, details.get("freshness", "unknown"))
        self.archive.prune(int(time.time()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "var/history")))
    parser.add_argument("--once", action="store_true", help="Collect one cycle (makes MTA network requests)")
    parser.add_argument("--status", action="store_true", help="Read existing archive status without collection")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--max-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--min-free-bytes", type=int, default=2 * 1024**3)
    args = parser.parse_args()
    if args.status:
        print(json.dumps(archive_status(args.state_dir), indent=2))
        return
    if args.poll_seconds < 30:
        parser.error("Poll interval must be at least 30 seconds")
    limits = Limits(retention_seconds=args.retention_days * 86400, max_bytes=args.max_bytes,
                    min_free_bytes=args.min_free_bytes)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    with HistoryArchive(args.state_dir, limits) as archive, httpx.Client(
        timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
        headers={"User-Agent": "MTA-Scan/history-1.0 (+https://stelioszach.com/demos/mta-scan/)"},
    ) as client:
        collector = HistoryCollector(archive)
        while not stop.is_set():
            started = time.monotonic()
            collector.collect(client, stop)
            if args.once:
                break
            stop.wait(max(1, args.poll_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
