#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
PY="${PYTHON_BIN:-python3}"

echo "[healthtest] base_url=$BASE_URL"

check_json() {
  local endpoint="$1"
  local code="$2"
  curl -fsS "$BASE_URL$endpoint" | "$PY" -c "$code"
}

check_json "/api/health" '
import json,sys
d=json.load(sys.stdin)
assert d.get("status")=="ok", d
assert "version" in d, d
print("[ok] /api/health")
'

check_json "/api/health/deep" '
import json,sys
d=json.load(sys.stdin)
assert d.get("status") in {"ok","degraded"}, d
checks=d.get("checks", {})
assert "db" in checks and "gtfs" in checks and "model" in checks, d
print("[ok] /api/health/deep")
'

check_json "/api/summary?window=15m" '
import json,sys
d=json.load(sys.stdin)
for k in ("stations_total","trains_active","anomalies_count","anomaly_rate_perc","last_updated_utc"):
    assert k in d, (k,d)
print("[ok] /api/summary")
'

check_json "/api/model/telemetry" '
import json,sys
d=json.load(sys.stdin)
assert d.get("status") in {"available","unavailable","error"}, d
print("[ok] /api/model/telemetry")
'

check_json "/api/heatmap?window=60m&route_id=All" '
import json,sys
d=json.load(sys.stdin)
assert d.get("type")=="FeatureCollection", d
assert "features" in d, d
print("[ok] /api/heatmap")
'

echo "[healthtest] PASS"
