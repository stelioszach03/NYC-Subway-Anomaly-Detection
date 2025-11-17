"""
Subway = no API key; Bus feeds require key.

Web references (verified):
- MTA Real-time Feeds landing: Accounts and API keys are no longer required to access these feeds.
  https://api.mta.info/

- Subway GTFS-RT endpoints (line-family):
  ACE   -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace
  BDFM  -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm
  G     -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g
  JZ    -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz
  NQRW  -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw
  L     -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l
  SI    -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si
  1234567 -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs
  (These are 8 line-family feeds.)

- Bus real-time (Bus Time APIs) still requires API key:
  https://new.mta.info/developers (Realtime data → Buses)
  http://bt.mta.info/wiki/Developers/Index
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple

import httpx
from google.transit import gtfs_realtime_pb2  # type: ignore
from sqlalchemy.orm import Session, sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Base, Score
from api.app.storage.session import get_engine


log = get_logger(__name__)


FEEDS: List[Tuple[str, str]] = [
    ("ACE", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace"),
    ("BDFM", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm"),
    ("G", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g"),
    ("JZ", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz"),
    ("NQRW", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw"),
    ("L", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l"),
    ("SI", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si"),
    ("1234567", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"),
]


def _http_get_with_retry(url: str, label: str, client: httpx.Client, max_attempts: int = 5) -> bytes | None:
    for attempt in range(1, max_attempts + 1):
        try:
            r = client.get(url, timeout=20)
            status = r.status_code
            if status == 200:
                log.bind(feed=label, status=status, attempt=attempt).debug("fetched feed")
                return r.content
            # Handle transient 403s: verify encoding and backoff
            if status == 403:
                if "%2F" not in url:
                    log.bind(feed=label, status=status).warning(
                        "403: url may need encoding; expected nyct%2Fgtfs-* path"
                    )
            log.bind(feed=label, status=status, attempt=attempt).warning("non-200 response")
        except Exception as e:  # network errors
            log.bind(feed=label, attempt=attempt).warning("http error: {}", repr(e))

        sleep_base = min(2 ** attempt, 30)
        jitter = random.uniform(0.3, 1.5)
        time.sleep(sleep_base * jitter)

    log.bind(feed=label).error("max attempts reached for feed")
    return None


def _parse_feed(content: bytes) -> Iterable[Tuple[str, str, int]]:
    """Yield (route_id, stop_id, arrival_epoch) from TripUpdates.

    Fallback: for VehiclePositions, use vehicle timestamp when present.
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(content)
    # TripUpdates preferred
    for entity in feed.entity:
        if entity.trip_update and entity.trip_update.trip:
            route_id = entity.trip_update.trip.route_id or ""
            for stu in entity.trip_update.stop_time_update:
                stop_id = stu.stop_id or ""
                arr = (stu.arrival.time or 0) if stu.HasField("arrival") else 0
                dep = (stu.departure.time or 0) if stu.HasField("departure") else 0
                t = arr or dep
                if route_id and stop_id and t:
                    yield route_id, stop_id, int(t)
        elif entity.vehicle and entity.vehicle.trip:
            route_id = entity.vehicle.trip.route_id or ""
            stop_id = entity.vehicle.stop_id or ""
            t = int(entity.vehicle.timestamp) if entity.vehicle.timestamp else 0
            if route_id and stop_id and t:
                yield route_id, stop_id, t


def _upsert_scores(session: Session, events: Iterable[Tuple[str, str, int]], last_seen: Dict[Tuple[str, str], int], window_sec: int = 300) -> int:
    """Aggregate minimal per (route, stop) arrival and write Score rows.

    For each (route, stop), keep earliest upcoming arrival for this cycle,
    compute naive headway against previous arrival, and insert a Score row
    (residual=0, anomaly_score=0) with ts set to arrival time.
    """
    # Keep earliest arrival per (route, stop) for this batch
    agg: Dict[Tuple[str, str], int] = {}
    now_epoch = int(time.time())
    for route_id, stop_id, t in events:
        # Only consider arrivals in the near future/past window
        if t < now_epoch - 3600 or t > now_epoch + 4 * 3600:
            continue
        key = (route_id, stop_id)
        if key not in agg or t < agg[key]:
            agg[key] = t

    count = 0
    for (route_id, stop_id), arr in agg.items():
        # naive headway calc
        prev = last_seen.get((route_id, stop_id))
        if prev is not None and arr > prev:
            headway = arr - prev
        else:
            headway = None
        last_seen[(route_id, stop_id)] = arr

        observed_ts = datetime.now(timezone.utc)
        event_ts = datetime.fromtimestamp(arr, tz=timezone.utc)
        session.add(
            Score(
                observed_ts=observed_ts,
                event_ts=event_ts,
                route_id=route_id,
                stop_id=stop_id,
                headway_sec=float(headway) if headway is not None else None,
                predicted_headway_sec=None,
                anomaly_score=0.0,
                residual=None,
                window_sec=window_sec,
            )
        )
        count += 1

    if count:
        session.commit()
    return count


def run() -> None:
    log.info("collector starting: subway GTFS-RT (no API key)")
    engine = get_engine()
    # Ensure tables exist (MVP safety)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        log.warning("could not ensure tables: {}", repr(e))

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    last_seen: Dict[Tuple[str, str], int] = {}

    with httpx.Client(headers={"User-Agent": "mta-subway-anomaly-scan/0.1"}) as client:
        while True:
            total_rows = 0
            for label, url in FEEDS:
                content = _http_get_with_retry(url, label, client)
                if not content:
                    continue
                try:
                    events = list(_parse_feed(content))
                except Exception as e:
                    log.bind(feed=label).warning("protobuf parse error: {}", repr(e))
                    continue
                if not events:
                    continue
                try:
                    with SessionLocal() as session:
                        rows = _upsert_scores(session, events, last_seen)
                        total_rows += rows
                        log.bind(feed=label, rows=rows).debug("ingested rows")
                except Exception as e:
                    log.bind(feed=label).warning("db write error: {}", repr(e))

            # sleep ~30s with small jitter
            sleep_s = 30.0 + random.uniform(-3.0, 3.0)
            log.bind(total_rows=total_rows).info("cycle complete; sleeping {:.1f}s", sleep_s)
            time.sleep(sleep_s)


def fetch_once_and_insert(limit_feeds: int = 2) -> int:
    """
    Pull a small set of Subway GTFS-RT feeds (no API key), parse minimal data,
    compute simple headway metrics, and insert rows into the scores table.
    Robust with retry/backoff, 5s timeout per request. Returns inserted rows count.
    """
    engine = get_engine()
    # Ensure schema exists
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        log.warning("could not ensure tables: {}", repr(e))

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    inserted_total = 0
    last_seen: Dict[Tuple[str, str], int] = {}

    headers = {"User-Agent": "mta-subway-anomaly-scan/test"}
    timeout = httpx.Timeout(5.0, connect=5.0)
    feeds = FEEDS[: max(0, int(limit_feeds)) or 1]
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            for label, url in feeds:
                content = _http_get_with_retry(url, label, client, max_attempts=3)
                if not content:
                    continue
                try:
                    events = list(_parse_feed(content))
                except Exception as e:
                    log.bind(feed=label).warning("protobuf parse error: {}", repr(e))
                    continue
                if not events:
                    continue
                try:
                    with SessionLocal() as session:
                        rows = _upsert_scores(session, events, last_seen, window_sec=300)
                        inserted_total += rows
                except Exception as e:
                    log.bind(feed=label).warning("db write error: {}", repr(e))
    except httpx.HTTPError as e:
        log.warning("network error: {}", repr(e))
        return 0
    return inserted_total


def main() -> None:
    run()


if __name__ == "__main__":
    main()
