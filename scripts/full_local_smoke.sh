#!/usr/bin/env bash
set -euo pipefail

echo "[smoke] Checking prerequisites..."

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# 1) Validate GTFS static presence
GTFS_DIR="${GTFS_DIR:-$ROOT_DIR/gtfs_subway}"
GTFS_ZIP="${GTFS_ZIP:-$GTFS_DIR/mta_gtfs_static.zip}"
if [[ ! -f "$GTFS_DIR/stops.txt" && ! -f "$GTFS_ZIP" ]]; then
  echo "[smoke] ERROR: Missing GTFS static. Provide stops.txt or mta_gtfs_static.zip in $GTFS_DIR" >&2
  exit 1
fi
echo "[smoke] GTFS OK at $GTFS_DIR"

# 2) Validate MAPBOX token
MAPBOX_TOKEN="${MAPBOX_TOKEN:-${NEXT_PUBLIC_MAPBOX_TOKEN:-}}"
if [[ -z "${MAPBOX_TOKEN}" ]]; then
  echo "[smoke] ERROR: MAPBOX_TOKEN (or NEXT_PUBLIC_MAPBOX_TOKEN) not set in env or infra/.env" >&2
  exit 1
fi
echo "[smoke] MAPBOX_TOKEN present"

# 3) Python dev setup
echo "[smoke] make setup-dev"
make setup-dev

# 4) Compose up core services and check API health
echo "[smoke] make compose-up"
make compose-up
sleep 3
echo "[smoke] curl API health"
curl -sf http://localhost:8000/api/health | jq . >/dev/null || {
  echo "[smoke] ERROR: API health check failed" >&2
  exit 1
}
echo "[smoke] running API healthtest suite"
make healthtest

# 5) Unit tests
echo "[smoke] running unit tests"
make test

# 6) Integration tests (host DB + live network)
echo "[smoke] running integration tests"
DB_URL="postgresql://postgres:postgres@localhost:5432/mta" TEST_ALLOW_NETWORK=1 make itest-host

# 7) UI dev (if not running), Playwright install, UI tests
echo "[smoke] ensuring UI dev server"
if ! curl -sSf http://localhost:3000 >/dev/null 2>&1; then
  echo "[smoke] starting UI dev in background"
  pushd ui >/dev/null
  npm install
  NEXT_PUBLIC_MAPBOX_TOKEN="$MAPBOX_TOKEN" npm run dev >/tmp/ui_dev.log 2>&1 &
  popd >/dev/null
  # wait up to 30s for UI
  for i in {1..30}; do
    if curl -sSf http://localhost:3000 >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi

echo "[smoke] installing Playwright deps"
pushd ui >/dev/null
npx playwright install --with-deps
echo "[smoke] running UI tests"
npm test
popd >/dev/null

echo "\n✅ Full local smoke passed"
