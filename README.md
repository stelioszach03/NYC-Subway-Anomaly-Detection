<div align="center">

# MTA-Scan · NYC Subway Anomaly Detection

**Real-time anomaly detection for the NYC Subway, powered by live GTFS-RT, online ML, and a production-grade command center.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![River](https://img.shields.io/badge/River-online%20ML-1f6feb?style=flat-square)](https://riverml.xyz/)
[![PyTorch](https://img.shields.io/badge/PyTorch-Shadow%20SSL-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PG16-FDB515?style=flat-square)](https://www.timescale.com/)
[![Mapbox](https://img.shields.io/badge/MapLibre-GL-396CB5?style=flat-square)](https://maplibre.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-f59e0b?style=flat-square)](LICENSE)

**[Landing](https://stelioszach.com/nyc-subway-anomaly/)**  ·  **[Live Command Center](https://stelioszach.com/nyc-subway-anomaly/live)**  ·  **[Next.js Ops UI](https://stelioszach.com/nyc-subway-anomaly/map)**  ·  **[API Health](https://stelioszach.com/nyc-subway-anomaly/api/health/deep)**

</div>

---

## What it does

MTA-Scan ingests **seven live MTA GTFS-Realtime protobuf feeds** every 30 seconds, persists each stop event into TimescaleDB, computes per-stop headway residuals, and scores anomalies in real time with a **hybrid online ML pipeline** (River + PyTorch shadow model). Operators triage incidents on a live map — every station ranked, color-coded, and contextualized with the model's prediction.

> Not a toy. **849 stations, 1 261 active trains, 8 192 scored rows, 741 critical anomalies** live at the time of this writing — all from real MTA feeds with zero fabrication.

## Highlights

- **Streaming GTFS-RT ingestion** — worker polls 7 MTA line-family feeds, deduplicates updates, and emits normalized stop events on a ~30s cadence.
- **Timescale hypertables** — minute-resolution stop events with fast range queries over observed vs predicted headway.
- **Online ML that retrains in place** — River `PARegressor` for headway prediction, `HalfSpaceTrees` for anomaly signal, ADWIN drift detector for model reset.
- **Self-supervised residual calibration** — rolling quantile scoring means the model needs **zero labels**.
- **PyTorch shadow model** — a denoising autoencoder trained on a sliding window, run in parallel as an A/B quality check and drift tracker.
- **Operator-grade observability** — `/api/health/deep` returns DB freshness, GTFS availability, model telemetry artifacts, and data age.
- **Two frontends**:
  - **Next.js 14 dashboard** (`/map`) — feature-rich operator console with KPIs, routes under pressure, severity distribution, incident ranking, and model telemetry panels.
  - **MapLibre GL command center** (`/live`) — new zero-dependency dark map with glass panels, heatmap layer, click-to-fly, and auto-refreshing incident stream.
- **Recruiter-ready landing page** (`/`) — live KPIs, pipeline explainer, 26-route grid, auto-refreshing anomaly feed.
- **Disk-safe model persistence** — retention-aware checkpoint saver that keeps only the N most recent bundles (default 5), fixed after a 37 GB memory leak from unbounded saves.
- **Full test suite** — unit + integration tests for health, scoring, collector, online ML, and telemetry.

## Architecture

```mermaid
flowchart LR
    A["MTA GTFS-RT<br/>7 line-family feeds"] --> B["Collector<br/>worker"]
    B --> C["TimescaleDB<br/>hypertables"]
    C --> D["Online Trainer<br/>River + ADWIN"]
    D --> C
    C --> E["SSL Shadow<br/>PyTorch DAE"]
    E --> F["Shadow Telemetry<br/>JSON"]
    C --> G["FastAPI"]
    G --> H["Next.js UI<br/>/map"]
    G --> I["MapLibre UI<br/>/live"]
    G --> J["Landing<br/>/"]
```

## Scoring logic

For each scored event the pipeline computes:

| Component | Weight | Description |
|-----------|:------:|-------------|
| SSL residual score | **0.50** | Rolling-quantile-calibrated residual of the `PARegressor` prediction |
| HalfSpaceTrees anomaly | **0.30** | Tree-based unsupervised anomaly score |
| Relative error | **0.20** | Absolute `|observed − predicted| / max(predicted, 60s)` |

Final:

```python
score = clip01(0.50 * ssl_residual + 0.30 * hst_score + 0.20 * relative_error)
```

Operational thresholds:

- `score ≥ 0.60` → **anomaly**
- `score ≥ 0.85` → **critical**

## API

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/health/deep` | DB freshness + GTFS + model telemetry |
| `GET` | `/api/summary?window=15m` | KPI card: stations, active trains, anomaly count/rate, timestamps |
| `GET` | `/api/anomalies?window=15m&route_id=All&limit=400` | Event-level anomaly rows with observed/event timestamp packs |
| `GET` | `/api/heatmap?ts=now&window=60m&route_id=All` | GeoJSON features (top-scoring event per stop in window) |
| `GET` | `/api/routes` | Distinct routes seen in last 24h |
| `GET` | `/api/stops` | Static GTFS stops with lat/lon |
| `GET` | `/api/model/telemetry` | River trainer telemetry |
| `GET` | `/api/model/telemetry/dl-shadow` | PyTorch shadow telemetry |

### Example

```bash
curl -s 'https://stelioszach.com/nyc-subway-anomaly/api/summary?window=15m' | jq
```

```json
{
  "window": "15m",
  "stations_total": 849,
  "trains_active": 1261,
  "anomalies_count": 999,
  "anomalies_high": 741,
  "anomaly_rate_perc": 12.19,
  "scored_rows": 8192,
  "last_updated_utc": "2026-04-15T17:34:58Z",
  "last_updated_ny": "2026-04-15T13:34:58-04:00"
}
```

## Quick Start

### Local Docker

```bash
git clone https://github.com/stelioszach03/NYC-Subway-Anomaly-Detection.git
cd NYC-Subway-Anomaly-Detection
cp infra/.env.example infra/.env

# Optional but recommended
echo "MAPBOX_TOKEN=pk.xxx" >> infra/.env

docker compose up -d --build db api worker trainer dl_shadow ui
```

Open:

- **Map UI**: http://localhost:3000/map
- **API Health**: http://localhost:8000/api/health/deep
- **Summary**: http://localhost:8000/api/summary?window=15m

### VPS / subpath deployment

```bash
docker compose -f docker-compose.vps.yml up -d --build
```

Exposed ports in the VPS profile:

| Service | Port | Purpose |
|---------|:----:|---------|
| API | `18600` | FastAPI |
| UI | `18700` | Next.js |

The UI is built with `NEXT_PUBLIC_BASE_PATH=/nyc-subway-anomaly` for reverse-proxy mounting.

## Six-service stack

| Service | Image | Role |
|---------|-------|------|
| `db` | `timescale/timescaledb:latest-pg16` | Hypertable event store |
| `worker` | Python 3.11 | GTFS-RT collector, 30 s cadence |
| `trainer` | Python 3.11 | River online ML, 5 s tick |
| `dl_shadow` | Python 3.11 + PyTorch | DAE shadow, 120 s tick |
| `api` | FastAPI + uvicorn | Read API + telemetry |
| `ui` | Next.js 14 standalone | Operator dashboard |

## Project Layout

```text
api/
├── app/
│   ├── main.py                     FastAPI app + CORS
│   ├── routers/                    health, summary, anomalies, heatmap, stops, routes, model
│   ├── models/                     SQLAlchemy Score model
│   ├── storage/                    Engine + session
│   └── core/                       Config, logging
worker/
├── collector.py                    GTFS-RT protobuf fetchers + dedupe
├── ml_online.py                    River trainer loop
├── ssl_shadow.py                   PyTorch DAE shadow loop
├── drift.py                        ADWIN + atomic retention-aware save_model
├── features.py                     Feature engineering
└── util.py                         Loguru
ui/
├── pages/                          Next.js pages (_app, map, index)
├── components/                     Map, KPIs, AnomalyTable, telemetry panels
└── lib/                            hooks, time, utils
landing/
├── index.html                      Public landing page (transit-ops editorial)
└── live.html                       MapLibre command center
tests/                              unit + integration suite
scripts/                            smoke + healthtest helpers
db/migrations/                      Postgres migrations
monitoring/                         (reserved)
```

## Configuration

All runtime settings come from `infra/.env` (copy from `infra/.env.example`):

| Variable | Purpose |
|----------|---------|
| `DB_URL` | Postgres DSN for TimescaleDB |
| `MODELS_DIR` | Model checkpoint directory (default `/data/gtfs/models`) |
| `MODEL_RETENTION` | Max checkpoints kept per prefix (default `5`) |
| `MODEL_TELEMETRY_PATH` | JSON for online trainer stats |
| `MODEL_DL_TELEMETRY_PATH` | JSON for shadow DAE stats |
| `MAPBOX_TOKEN` | Optional, enables Mapbox streets basemap in `/map` |
| `APP_VERSION` | Reported in `/api/health` |

## Observability

- **`/api/health/deep`** returns:
  - DB connectivity + score row counts + last observed timestamp + freshness flag
  - GTFS static file status + stop count
  - Online trainer telemetry (rows seen/updated, drift events, MAE EMA, residual quantiles, backlog)
  - DL shadow telemetry (reconstruction error p90/p99, correlation with online score)
- **Retention logging** — every stale checkpoint deletion is logged with prefix and count
- **Deep-health test script** — `scripts/healthtest.sh` for CI / operators

## Testing

```bash
make setup-dev
make test                                   # unit
DB_URL=postgresql://postgres:postgres@localhost:5432/mta \
TEST_ALLOW_NETWORK=1 make itest-host        # integration (requires local DB)
./scripts/healthtest.sh http://localhost:8000
```

## Roadmap

- [ ] Kafka streaming backbone for cross-data-source event fusion
- [ ] Temporal GNN for stop-topology-aware anomaly propagation
- [ ] Incident playback for forensic replay
- [ ] Multi-agency expansion (LIRR, Metro-North, NJ Transit)

---

<div align="center">

Built by **[Stelios Zacharioudakis](https://stelioszach.com)** · ML Engineer & Researcher · Athens → Toronto

[Portfolio](https://stelioszach.com) · [GitHub](https://github.com/stelioszach03) · [LinkedIn](https://www.linkedin.com/in/stylianos-georgios-zacharioudakis-47024428a)

</div>
