<!--
Web Check (verified on current MTA official pages):

1) Subway GTFS-RT access policy:
   - The official MTA Real-time Data Feeds page states: "Accounts and API keys are no longer required to access these feeds." — https://api.mta.info/

2) Current Subway GTFS-RT feed endpoints (GTFS-RT by line family):
   - ACE: https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace
   - BDFM: https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm
   - G:   https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g
   - JZ:  https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz
   - NQRW:https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw
   - L:   https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l
   - SI:  https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si
   - 1234567 (numbered lines): https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs

3) Bus GTFS-RT policy (Bus Time APIs):
   - The MTA Developers page states: "Real-time bus data is provided via the Bus Time set of APIs. You will need to create an account and use an API key to access the feeds." — https://new.mta.info/developers (see Realtime data → Buses; Bus Time docs: http://bt.mta.info/wiki/Developers/Index)
-->

## NYC Subway Anomaly Detection (GTFS-RT + Online ML)

![CI](https://img.shields.io/badge/CI-green?style=flat) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

- Real-time GTFS-RT ingestion (Subway; no API key required)
- Online learning with River (residuals + anomaly score)
- Drift detection and rolling updates
- Next.js + Mapbox UI for live heatmap and anomaly table

```mermaid
flowchart LR
  MTA[GTFS-RT Feeds] -->|collector| DB[(TimescaleDB)]
  DB -->|features| Trainer[Online ML (River)]
  Trainer --> DB
  DB --> API[FastAPI]
  API --> UI[Next.js + Mapbox]
```

Notes
- Subway feeds require no API key; Bus feeds do.
- GTFS static should be available under `/data/gtfs` (mounted from `gtfs_subway/`).

### Quickstart (Docker)
1) Place GTFS static ZIP or `stops.txt` in `gtfs_subway/` (repo-relative) or `infra/data/gtfs`.
2) `cp infra/.env.example infra/.env` and set `MAPBOX_TOKEN`.
3) `docker compose up -d db api worker trainer ui`.
4) API: `http://localhost:8000/api/health` • UI: `http://localhost:3000/map`.

### Local Development & Tests
- `make setup-dev` → create venv and install dev dependencies
- Unit tests: `make test`
- Integration (live feeds): `DB_URL=postgresql://postgres:postgres@localhost:5432/mta TEST_ALLOW_NETWORK=1 make itest-host`
- UI tests (Playwright):
  - `cd ui && npm install && npm run dev &`
  - `npx playwright install --with-deps && npm test`
- Full smoke (unit + integration + UI): `./scripts/full_local_smoke.sh`

### API Endpoints (selected)
- `GET /api/summary`
  - Response includes `last_updated_utc`, `last_updated_epoch_ms`, `last_updated_ny` computed from MAX(observed_ts).
  - Example:
    ```json
    {
      "window": "15m",
      "stations_total": 421,
      "trains_active": 128,
      "anomalies_count": 37,
      "anomalies_high": 12,
      "anomaly_rate_perc": 8.9,
      "last_updated_utc": "2025-09-10T20:31:02Z",
      "last_updated_epoch_ms": 1757536262000,
      "last_updated_ny": "2025-09-10T16:31:02-04:00"
    }
    ```
- `GET /api/anomalies?window=15m&route_id=All`
  - Each item includes observed_* and event_* timestamp packs.
  - Example item:
    ```json
    {
      "route_id": "A",
      "stop_id": "A12N",
      "stop_name": "Inwood-207 St",
      "anomaly_score": 0.72,
      "residual": 180.0,
      "observed_ts_utc": "2025-09-10T20:30:55Z",
      "observed_ts_epoch_ms": 1757536255000,
      "observed_ts_ny": "2025-09-10T16:30:55-04:00",
      "event_ts_utc": "2025-09-10T20:32:00Z",
      "event_ts_epoch_ms": 1757536320000,
      "event_ts_ny": "2025-09-10T16:32:00-04:00"
    }
    ```
- `GET /api/heatmap?window=60m`
  - Returns a GeoJSON FeatureCollection; each feature.properties contains anomaly_score, residual, observed_* (primary), and optional event_*.
- `GET /api/stops`, `GET /api/routes`
  - Served with `Cache-Control: public, max-age=600` and weak `ETag`.

### UI Notes
- Map has two stable layers: stations under anomalies.
- Anomaly circles use `scoreToColor(score)` and radius interpolation: 0→4, 0.5→6, 0.85→8, 1.0→10 (opacity 0.8).
- Popups show “Observed: … • … ago” and optional “ETA: …”.
- Table shows “Observed (NYC)”, relative time, and muted ETA.
- Next.js rewrite proxies `/api` to `:8000` (see `ui/next.config.js`).

### Time Semantics
- `observed_ts`: when the datapoint was observed/ingested.
- `event_ts`: the ETA/scheduled time from GTFS‑RT (may be null).

### Screenshots
- `docs/ui-map.png` — map + side panel
- `docs/ui-table.png` — table with Observed/ETA

### License
MIT — see [LICENSE](LICENSE).
