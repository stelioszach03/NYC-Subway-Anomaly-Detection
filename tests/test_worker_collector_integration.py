from __future__ import annotations

import os
import pytest


pytestmark = [pytest.mark.integration]


def _network_allowed() -> bool:
    return os.environ.get("TEST_ALLOW_NETWORK") == "1"


def _db_reachable() -> bool:
    try:
        from api.app.storage.session import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.timeout(10)
def test_collector_ingests_one_feed():
    if not _network_allowed():
        pytest.skip("TEST_ALLOW_NETWORK!=1; skipping live network test")
    if not _db_reachable():
        pytest.skip("DB not reachable; run docker compose up db or set DB_URL")

    from worker.collector import fetch_once_and_insert
    inserted = fetch_once_and_insert(limit_feeds=1)
    assert inserted > 0
