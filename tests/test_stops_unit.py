import pytest


@pytest.mark.usefixtures("test_client")
def test_stops_unit_has_data(test_client, has_gtfs):
    if not has_gtfs:
        pytest.skip("GTFS static not available; skipping stops test")

    r = test_client.get("/api/stops")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    sample = data[0]
    for k in ("stop_id", "stop_name", "lat", "lon"):
        assert k in sample

