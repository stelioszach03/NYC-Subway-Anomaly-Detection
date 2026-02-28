# NYC Subway Anomaly Detection

Real-time anomaly intelligence for NYC Subway operations using GTFS-RT, online machine learning, and an interactive monitoring UI.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](#)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white)](#)
[![PyTorch](https://img.shields.io/badge/PyTorch-Shadow%20SSL-EE4C2C?logo=pytorch&logoColor=white)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Live demo: `https://stelioszach.com/nyc-subway-anomaly/map`

## Why This Project

Subway service irregularities often emerge as headway disruptions before they appear in aggregate metrics.  
This project ingests live GTFS-RT feed updates, learns headway behavior online, and surfaces anomalous stops/routes in a production-style command center.

## Core Capabilities

- Real-time ingestion from MTA Subway GTFS-RT line-family feeds
- TimescaleDB-backed event store for scored headway observations
- Online ML scoring with River:
  - `PARegressor` for headway prediction
  - `HalfSpaceTrees` for anomaly signal
  - ADWIN-based drift detection and model reset
- Self-supervised residual calibration using rolling quantiles (no labels required)
- PyTorch self-supervised shadow model (denoising autoencoder) for advanced telemetry and cross-checking
- FastAPI endpoints for summary, anomalies, heatmap, telemetry, and health
- Next.js + Mapbox operational UI with:
  - live map overlays
  - top anomalies table
  - model telemetry panels
  - base-path aware deployment (for reverse proxy/Nginx)

## Architecture

```mermaid
flowchart LR
  A["MTA GTFS-RT Subway Feeds"] --> B["Collector Worker"]
  B --> C["TimescaleDB and Postgres"]
  C --> D["Online Trainer (River)"]
  D --> C
  C --> E["FastAPI"]
  E --> F["Next.js UI and Mapbox"]
  C --> G["PyTorch SSL Shadow Worker"]
  G --> H["DL Shadow Telemetry JSON"]
  E --> I["Model Telemetry Endpoints"]
```

## Tech Stack

- Backend: Python, FastAPI, SQLAlchemy
- Data: TimescaleDB/Postgres
- Streaming input: GTFS-Realtime protobuf feeds
- Online ML: River
- Deep Learning (shadow): PyTorch
- Frontend: Next.js, React, Tailwind, Mapbox GL
- Infra: Docker Compose

## Repository Layout

```text
api/          FastAPI app (routes, models, storage, config)
worker/       Collector + online trainer + SSL shadow worker
ui/           Next.js dashboard (/map)
tests/        Unit + integration tests
scripts/      Health/smoke helpers
infra/        Environment templates
docker/       Dockerfiles
docs/         Documentation assets
```

## Quick Start (Local Docker)

### Prerequisites

- Docker + Docker Compose
- Optional Mapbox token (map still has fallback basemap without token)
- GTFS static data (`mta_gtfs_static.zip` or `stops.txt`) under `gtfs_subway/`

### Steps

1. Copy environment template:
   ```bash
   cp infra/.env.example infra/.env
   ```
2. Set at least:
   - `MAPBOX_TOKEN=...` (recommended)
   - `DB_URL=postgresql://postgres:postgres@db:5432/mta` (default in compose)
3. Start services:
   ```bash
   docker compose up -d --build db api worker trainer ui
   ```
4. Open:
   - API health: `http://localhost:8000/api/health`
   - UI map: `http://localhost:3000/map`

## VPS / Base-Path Deployment

For deployment behind `/nyc-subway-anomaly`:

```bash
docker compose -f docker-compose.vps.yml up -d --build
```

Default exposed ports in this profile:

- API: `18600 -> 8000`
- UI: `18700 -> 3000`

The UI is built with `NEXT_PUBLIC_BASE_PATH=/nyc-subway-anomaly`.

## Repository Hygiene

- Runtime model artifacts under `gtfs_subway/models/` are intentionally git-ignored.
- Secrets are injected via environment variables (`infra/.env`) and are never committed.

## API Reference (Selected)

- `GET /api/health`  
  Liveness status.
- `GET /api/health/deep`  
  Deep checks for DB freshness, GTFS availability, and model telemetry artifacts.
- `GET /api/summary?window=15m`  
  Dashboard KPIs (`stations_total`, `trains_active`, `anomalies_count`, `anomaly_rate_perc`, timestamps).
- `GET /api/anomalies?window=15m&route_id=All&limit=400`  
  Event-level anomaly rows with observed/event timestamp packs.
- `GET /api/heatmap?window=15m&route_id=All&ts=now`  
  GeoJSON features for map rendering.  
  Uses top-scoring event per stop in the selected window.
- `GET /api/stops`, `GET /api/routes`
- `GET /api/model/telemetry`
- `GET /api/model/telemetry/dl-shadow`

## Scoring Logic

For each scored event, the online trainer computes:

- prediction residual
- self-supervised residual score (rolling quantile calibration)
- tree-based anomaly signal (HalfSpaceTrees)
- relative error component

Final anomaly score:

```text
score = clip01(
  0.50 * ssl_residual_score
  + 0.30 * hst_score
  + 0.20 * relative_error_score
)
```

Operational thresholds:

- `>= 0.60`: anomaly
- `>= 0.85`: high anomaly

## Testing & Quality Gates

- Dev setup:
  ```bash
  make setup-dev
  ```
- Unit tests + lint:
  ```bash
  make test
  ```
- Integration tests (host DB):
  ```bash
  DB_URL=postgresql://postgres:postgres@localhost:5432/mta TEST_ALLOW_NETWORK=1 make itest-host
  ```
- API health smoke:
  ```bash
  ./scripts/healthtest.sh http://localhost:8000
  ```

## Data Access Notes

- MTA Subway GTFS-RT feeds: no API key required.
- MTA Bus real-time APIs: API key required (separate policy).

## License

MIT. See [LICENSE](LICENSE).
