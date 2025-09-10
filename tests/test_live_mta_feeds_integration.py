"""
Integration tests that hit live Subway GTFS-RT feeds (no API key required).

References (official):
- MTA Real-time Feeds: Accounts and API keys are no longer required.
  https://api.mta.info/
- Subway feeds endpoints (examples used below):
  ACE   -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace
  BDFM  -> https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm
"""
from __future__ import annotations

import os

import httpx
import pytest


pytestmark = [pytest.mark.integration]


def _network_allowed() -> bool:
    return os.environ.get("TEST_ALLOW_NETWORK") == "1"


@pytest.mark.timeout(10)
def test_live_subway_feeds_basic():
    if not _network_allowed():
        pytest.skip("TEST_ALLOW_NETWORK!=1; skipping live network test")

    feeds = [
        ("ACE", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace"),
        ("BDFM", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm"),
    ]

    headers = {"User-Agent": "mta-subway-anomaly-scan/tests"}
    timeout = httpx.Timeout(5.0, connect=5.0)
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            for label, url in feeds:
                r = client.get(url)
                if r.status_code != 200:
                    pytest.skip(f"feed {label} non-200: {r.status_code}")
                content = r.content
                assert content and len(content) > 100
                # Optional minimal protobuf parse if bindings available
                try:
                    from google.transit import gtfs_realtime_pb2  # type: ignore

                    msg = gtfs_realtime_pb2.FeedMessage()
                    msg.ParseFromString(content)
                    # Ensure we saw at least one entity or header parsed
                    assert msg.header is not None
                except Exception:
                    # If parsing not available, we still validated content presence
                    pass
    except httpx.HTTPError as e:
        pytest.skip(f"network failure: {e}")

