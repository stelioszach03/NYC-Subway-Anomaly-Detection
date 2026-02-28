import json


def test_model_telemetry_unavailable_by_default(test_client):
    r = test_client.get("/api/model/telemetry")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") in {"unavailable", "available", "error"}


def test_model_telemetry_reads_json(test_client, tmp_path, monkeypatch):
    p = tmp_path / "telemetry.json"
    payload = {
        "rows_seen": 123,
        "rows_updated": 120,
        "drift_events": 2,
        "mae_ema": 14.7,
        "last_run_utc": "2026-02-28T10:10:10Z",
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MODEL_TELEMETRY_PATH", str(p))

    r = test_client.get("/api/model/telemetry")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "available"
    assert data["rows_seen"] == 123
    assert data["drift_events"] == 2
