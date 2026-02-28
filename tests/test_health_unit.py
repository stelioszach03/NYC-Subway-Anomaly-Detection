def test_health_unit(test_client):
    r = test_client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert "version" in data


def test_health_deep_unit_shape(test_client):
    r = test_client.get("/api/health/deep")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") in {"ok", "degraded"}
    assert "checks" in data
    assert "db" in data["checks"]
    assert "gtfs" in data["checks"]
    assert "model" in data["checks"]
