"""Bounded official MTA subway-alert history, separate from model predictions.

One invocation polls once. A systemd timer schedules it; no paid service is used.
Raw full snapshots and normalized revisions retain response-availability time.
Only an allowlisted current summary is made readable by the public adapter.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

import httpx
from google.transit import gtfs_realtime_pb2 as gtfs
from google.protobuf.message import DecodeError

SOURCE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"
SCHEMA = "mta-official-service-alerts-v1"
MAX_FEED_BYTES = 4 * 1024**2
MAX_AGE = 600
MAX_PUBLIC_ALERTS = 100


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def english(value):
    # Prefer the published plain-text English field; never render the HTML variant.
    for item in value.translation:
        if item.language in ("en", "en-US", "en-GB", "") and item.text:
            return item.text
    return ""


def active_interval(periods, now):
    if not periods:
        return {"start": None, "end": None}
    return next(
        (p for p in periods if (p["start"] is None or p["start"] <= now) and (p["end"] is None or now < p["end"])), None
    )


def decode(payload, now):
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("oversized_feed")
    feed = gtfs.FeedMessage()
    feed.ParseFromString(payload)
    if not feed.IsInitialized() or not feed.header.HasField("timestamp"):
        raise ValueError("missing_source_timestamp")
    if feed.header.incrementality != gtfs.FeedHeader.FULL_DATASET:
        raise ValueError("unsupported_incremental_feed")
    if len(feed.entity) > 2000:
        raise ValueError("too_many_alerts")
    alerts = []
    seen = set()
    for entity in feed.entity:
        if entity.is_deleted or not entity.HasField("alert"):
            continue
        if not entity.id or entity.id in seen or len(entity.id) > 160:
            raise ValueError("invalid_alert_identity")
        seen.add(entity.id)
        a = entity.alert
        periods = [
            {"start": int(p.start) if p.HasField("start") else None, "end": int(p.end) if p.HasField("end") else None}
            for p in a.active_period
        ]
        if len(periods) > 1024 or any(
            p["start"] is not None and p["end"] is not None and p["end"] <= p["start"] for p in periods
        ):
            raise ValueError("invalid_active_period")
        routes = sorted({e.route_id for e in a.informed_entity if e.route_id})
        if len(routes) > 64 or any(len(r) > 16 for r in routes):
            raise ValueError("invalid_route")
        kind = (
            "planned_work"
            if entity.id.startswith("lmm:planned_work:")
            else "service_alert"
            if entity.id.startswith("lmm:alert:")
            else "other"
        )
        item = {
            "id": entity.id,
            "kind": kind,
            "routes": routes,
            "header": english(a.header_text),
            "description": english(a.description_text),
            "active_periods": periods,
        }
        item["revision_sha256"] = hashlib.sha256(canonical(item).encode()).hexdigest()
        alerts.append(item)
    return int(feed.header.timestamp), alerts


class Archive:
    def __init__(self, state, max_bytes=256 * 1024**2):
        self.path = Path(state) / "alerts.sqlite3"
        self.max_bytes = max_bytes
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        pages = max_bytes // self.db.execute("PRAGMA page_size").fetchone()[0]
        self.db.execute(f"PRAGMA max_page_count={int(pages)}")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS snapshots(sha TEXT PRIMARY KEY, source_ts INTEGER NOT NULL, payload BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS polls(id INTEGER PRIMARY KEY, available_ts INTEGER NOT NULL, status TEXT NOT NULL, sha TEXT);
          CREATE INDEX IF NOT EXISTS poll_time ON polls(available_ts);
          CREATE TABLE IF NOT EXISTS revisions(alert_id TEXT NOT NULL, revision_sha TEXT NOT NULL,
            first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, content TEXT NOT NULL,
            PRIMARY KEY(alert_id,revision_sha));
        """)

    def close(self):
        self.db.close()

    def prune(self, now):
        with self.db:
            self.db.execute("DELETE FROM polls WHERE available_ts < ?", (now - 7 * 86400,))
            self.db.execute(
                "DELETE FROM polls WHERE id IN (SELECT id FROM polls ORDER BY id DESC LIMIT -1 OFFSET 10080)"
            )
            self.db.execute("DELETE FROM revisions WHERE last_seen < ?", (now - 30 * 86400,))
            self.db.execute(
                "DELETE FROM revisions WHERE rowid IN (SELECT rowid FROM revisions ORDER BY last_seen DESC LIMIT -1 OFFSET 10000)"
            )
            self.db.execute("DELETE FROM snapshots WHERE sha NOT IN (SELECT sha FROM polls WHERE sha IS NOT NULL)")
        if self.path.stat().st_size > self.max_bytes * 0.85:
            with self.db:
                self.db.execute("DELETE FROM polls WHERE id IN (SELECT id FROM polls ORDER BY id LIMIT 720)")
                self.db.execute("DELETE FROM snapshots WHERE sha NOT IN (SELECT sha FROM polls WHERE sha IS NOT NULL)")
                self.db.execute(
                    "DELETE FROM revisions WHERE rowid IN (SELECT rowid FROM revisions ORDER BY last_seen LIMIT 500)"
                )
            self.db.execute("VACUUM")
        else:
            self.db.execute("PRAGMA incremental_vacuum(256)")

    def record(self, payload, source_ts, alerts, now, status):
        sha = hashlib.sha256(payload).hexdigest() if payload is not None else None
        with self.db:
            if payload is not None:
                self.db.execute(
                    "INSERT OR IGNORE INTO snapshots VALUES (?,?,?)", (sha, source_ts, gzip.compress(payload))
                )
            self.db.execute("INSERT INTO polls(available_ts,status,sha) VALUES (?,?,?)", (now, status, sha))
            for item in alerts:
                self.db.execute(
                    "INSERT INTO revisions VALUES (?,?,?,?,?) ON CONFLICT(alert_id,revision_sha) "
                    "DO UPDATE SET last_seen=excluded.last_seen",
                    (item["id"], item["revision_sha256"], now, now, canonical(item)),
                )
        return sha

    def stats(self):
        row = self.db.execute("SELECT COUNT(*),MIN(available_ts),MAX(available_ts) FROM polls").fetchone()
        return {
            "retained_polls": row[0],
            "first_receipt_ts": row[1],
            "last_receipt_ts": row[2],
            "retained_revisions": self.db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0],
            "database_bytes": self.path.stat().st_size,
            "max_database_bytes": self.max_bytes,
        }


def fetch(client):
    started = time.monotonic()
    body = bytearray()
    with client.stream("GET", SOURCE) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if time.monotonic() - started > 20 or len(body) + len(chunk) > MAX_FEED_BYTES:
                raise ValueError("bounded_fetch_exceeded")
            body.extend(chunk)
    return bytes(body)


def publish(state, value):
    folder = Path(state) / "public"
    folder.mkdir(mode=0o755, exist_ok=True)
    os.chmod(folder, 0o755)
    data = (canonical(value) + "\n").encode()
    while len(data) > 256 * 1024 and value.get("alerts"):
        value["alerts"].pop()
        value["display_truncated"] = True
        data = (canonical(value) + "\n").encode()
    if len(data) > 256 * 1024:
        raise ValueError("oversized_public_summary")
    tmp = folder / "summary.json.tmp"
    with tmp.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(tmp, 0o644)
    tmp.replace(folder / "summary.json")


def run_once(state, *, client=None, now_fn=time.time):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running"}
        if shutil.disk_usage(state).free < 2 * 1024**3:
            raise OSError("free_space_reserve")
        archive = Archive(state)
        try:
            archive.prune(int(now_fn()))
            try:
                if client is None:
                    with httpx.Client(
                        timeout=httpx.Timeout(15, connect=5),
                        follow_redirects=False,
                        headers={"User-Agent": "MTA-Scan/1.0 service-alert-context"},
                    ) as owned:
                        payload = fetch(owned)
                else:
                    payload = fetch(client)
                now = int(now_fn())  # Response available, never request-start time.
                source_ts, items = decode(payload, now)
                fresh = -30 <= now - source_ts <= MAX_AGE
                status = "ok" if fresh else "stale"
                sha = archive.record(payload, source_ts, items, now, status)
                current = []
                for item in items:
                    period = active_interval(item["active_periods"], now)
                    if period is not None:
                        current.append(
                            {
                                "id": item["id"],
                                "kind": item["kind"],
                                "routes": item["routes"],
                                "header": item["header"][:400],
                                "description": item["description"][:1200],
                                "description_truncated": len(item["description"]) > 1200,
                                "active_period": period,
                                "revision_sha256": item["revision_sha256"],
                            }
                        )
                current.sort(key=lambda a: (a["kind"] != "service_alert", a["id"]))
                public = {
                    "schema": SCHEMA,
                    "status": status,
                    "generated_ts": now,
                    "source_ts": source_ts,
                    "valid_until_ts": min(now + MAX_AGE, source_ts + MAX_AGE),
                    "source_url": SOURCE,
                    "snapshot_sha256": sha,
                    "total_feed_alerts": len(items),
                    "active_alert_count": len(current),
                    "display_truncated": len(current) > MAX_PUBLIC_ALERTS,
                    "alerts": current[:MAX_PUBLIC_ALERTS] if fresh else [],
                }
            except (httpx.HTTPError, ValueError, DecodeError, sqlite3.Error):
                # Keep operational error details out of the public response. Protobuf
                # DecodeError is intentionally handled as a failed collection attempt.
                now = int(now_fn())
                archive.record(None, None, [], now, "error")
                public = {
                    "schema": SCHEMA,
                    "status": "unavailable",
                    "generated_ts": now,
                    "source_ts": None,
                    "valid_until_ts": None,
                    "source_url": SOURCE,
                    "alerts": [],
                    "total_feed_alerts": None,
                    "active_alert_count": None,
                    "display_truncated": False,
                }
            archive.prune(now)
            public.update(
                {
                    "archive": archive.stats(),
                    "is_model_prediction": False,
                    "is_incident_ground_truth": False,
                    "note": "Official MTA messages provide service context. They may be delayed or revised; they are not validated incident labels or predictions from this model.",
                }
            )
            publish(state, public)
            return public
        finally:
            archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_once(args.state_dir)
    print(json.dumps({"status": result["status"], "active_alert_count": result.get("active_alert_count")}))
