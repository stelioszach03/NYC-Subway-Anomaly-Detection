# MTA-Scan

**[Live demo — Explore the subway monitor](https://stelioszach.com/demos/mta-scan/)** · [Deployed adapter and UI source](https://github.com/stelioszach03/stelioszach-portfolio/tree/main/demo-services/mta-scan)

The live portfolio workspace uses a separately maintained CPU adapter for public MTA feed observations and a clearly separated frozen replay. This repository contains the broader experimental stack and replay tooling, not the exact deployed service. Neither the live scores nor the small constructed replay establish validated transit-incident detection.

A streaming-data prototype for NYC Subway headway anomaly detection. It includes GTFS-Realtime collection, online feature/model updates, a FastAPI service, a dashboard and a small offline replay evaluation.

**Status:** engineering prototype. The repository supports local replay and a deployable stack; it does not establish an operated production service or validated transit incident detection.

## Architecture

GTFS-Realtime collector → per-stop headway features → online River model and heuristic baselines → database/API → dashboard. An optional PyTorch denoising-autoencoder shadow component is separate from the default local replay. An anomaly score is not a root-cause diagnosis.

The independent [raw history collector](docs/HISTORICAL_COLLECTION.md) preserves
original GTFS-RT snapshots and per-feed freshness in a bounded SQLite archive.
It can run continuously without the experimental stack or a live-model restart.
An optional daily exporter produces typed Parquet for completed UTC days with
verified hashes/counts and independent 90-day/10-GiB retention. This is
prospective collection infrastructure, not an existing longitudinal benchmark,
incident label source or forecasting result.

## Recorded replay evidence

The [sample CSV](evaluation/data/sample_subway_headways.csv) contains 216 representative scenario rows, 16 positive labels and three constructed incident scenarios. It is a demonstration fixture, **not an official MTA-labeled benchmark**. See the [data card](docs/DATA_CARD.md).

| Method | False-alarm rate | Precision@20 | Recall@20 | Detected scenarios |
|---|---:|---:|---:|---:|
| Online model | 0.030 | 0.80 | 1.000 | 3/3 |
| z-score | 0.010 | 0.50 | 0.625 | 3/3 |
| EWMA | 0.005 | 0.50 | 0.625 | 3/3 |
| Fixed threshold | 0.000 | 0.50 | 0.625 | 1/3 |

These recorded [metrics](docs/generated/replay/metrics.json) illustrate a sensitivity/false-alarm trade-off at threshold0.6. There are no confidence intervals or large-scale quality claims. The legacy JSON field `mean_reciprocal_rank` averages reciprocal ranks of **all positive rows**; it is not standard query-level MRR and should not be compared with that metric.

## Offline checks and replay

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q -m 'not integration'
PYTHONPATH=. python scripts/run_replay_eval.py \
  --input evaluation/data/sample_subway_headways.csv --out-dir /tmp/mta-replay
```

With Node.js installed, `node --test tests/landing_feed.test.mjs` also checks that the landing page clears stale incident rows and starts without fabricated observations.

Replay reads the tracked fixture and writes new local artifacts. Stable BLAKE2 feature hashing avoids dependence on Python's randomized process hash. Unit checks use an in-memory database; live Postgres/MTA integration tests are separate and are not included in the command above.

For the complete stack, inspect the Compose environment and ports before running `docker compose up -d --build db api worker trainer dl_shadow ui`. This starts collectors and makes network calls. Docker must be available; static GTFS input and any external context credentials must be configured separately. The replay command does not start that stack.

## Limits

- Only three constructed incident scenarios; no evidence of transit-scale performance or causal lead-time benefit.
- Live feeds may be stale, incomplete or inconsistent. Weather/service-alert context is optional and needs its own source.
- Static GTFS data are absent, so map/stops views need separately prepared input.
- The PyTorch shadow model is installed in the worker image, not the minimal local requirements.
- No uptime/SLA, calibrated risk, official MTA endorsement or production deployment claim is made.

[MIT license](LICENSE); MTA data usage terms remain separate.
