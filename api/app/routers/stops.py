from __future__ import annotations

import csv
import io
import os
import zipfile
from typing import Dict, List
import hashlib

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ..core.config import get_settings
from ..core.logging import get_logger


router = APIRouter(prefix="/stops", tags=["stops"]) 

_CACHED_STOPS: List[Dict] | None = None
_CACHED_ROUTES: List[str] | None = None
_CACHED_STOPS_ETAG: str | None = None


def _extract_stops_from_reader(reader: csv.DictReader) -> List[Dict]:
    rows: List[Dict] = []
    seen: set[str] = set()
    for row in reader:
        sid = (row.get("stop_id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        name = (row.get("stop_name") or "").strip()
        lat_s = row.get("stop_lat") or ""
        lon_s = row.get("stop_lon") or ""
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except Exception:
            continue
        rows.append({
            "stop_id": sid,
            "stop_name": name,
            "lat": lat,
            "lon": lon,
            "routes": [],
        })
    return rows


def _load_from_zip(zip_path: str, filename: str) -> List[Dict]:
    log = get_logger(__name__)
    with zipfile.ZipFile(zip_path) as zf:
        target_name = None
        for info in zf.infolist():
            if info.filename.endswith(filename):
                target_name = info.filename
                break
        if not target_name:
            log.warning("%s not found in zip: %s", filename, zip_path)
            return []
        with zf.open(target_name, "r") as f:
            text = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.DictReader(text)
            if filename == "stops.txt":
                return _extract_stops_from_reader(reader)
            else:
                return [dict(r) for r in reader]


def _load_from_dir(dir_path: str, filename: str) -> List[Dict]:
    log = get_logger(__name__)
    path = os.path.join(dir_path, filename)
    if not os.path.exists(path):
        log.warning("%s not found in dir: %s", filename, dir_path)
        return []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if filename == "stops.txt":
            return _extract_stops_from_reader(reader)
        else:
            return [dict(r) for r in reader]


def _load_routes_from_static() -> List[str]:
    s = get_settings()
    routes: List[Dict] = []
    if s.MTA_GTFS_STATIC_PATH and os.path.exists(s.MTA_GTFS_STATIC_PATH) and zipfile.is_zipfile(s.MTA_GTFS_STATIC_PATH):
        routes = _load_from_zip(s.MTA_GTFS_STATIC_PATH, "routes.txt")
    else:
        routes = _load_from_dir(s.GTFS_STATIC_DIR, "routes.txt")
    vals = []
    for r in routes:
        rid = (r.get("route_id") or "").strip()
        if rid:
            vals.append(rid)
    return sorted(list({*vals}))


def _load_stops() -> List[Dict]:
    global _CACHED_STOPS
    if _CACHED_STOPS is not None:
        return _CACHED_STOPS
    s = get_settings()
    log = get_logger(__name__)
    stops: List[Dict] = []
    if s.MTA_GTFS_STATIC_PATH and os.path.exists(s.MTA_GTFS_STATIC_PATH) and zipfile.is_zipfile(s.MTA_GTFS_STATIC_PATH):
        stops = _load_from_zip(s.MTA_GTFS_STATIC_PATH, "stops.txt")
    else:
        stops = _load_from_dir(s.GTFS_STATIC_DIR, "stops.txt")
    _CACHED_STOPS = stops
    # compute weak ETag based on ids and count
    try:
        concat = ",".join(sorted([s.get("stop_id", "") for s in stops])).encode("utf-8")
        h = hashlib.sha1(concat).hexdigest()[:16]
        global _CACHED_STOPS_ETAG
        _CACHED_STOPS_ETAG = f'W/"stops-{len(stops)}-{h}"'
    except Exception:
        _CACHED_STOPS_ETAG = None
    log.info("loaded {} stops", len(stops))
    return stops


def prime_stops_cache() -> None:
    _ = _load_stops()


class StopOut(BaseModel):
    stop_id: str
    stop_name: str | None = None
    lat: float
    lon: float
    routes: List[str] | None = None


@router.get("", response_model=List[StopOut])
async def list_stops(response: Response) -> List[Dict]:
    data = _load_stops()
    # caching headers
    response.headers["Cache-Control"] = "public, max-age=600"
    if _CACHED_STOPS_ETAG:
        response.headers["ETag"] = _CACHED_STOPS_ETAG
    return data
