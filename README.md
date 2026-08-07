# MTA-Scan

Unsupervised anomaly detection on live NYC Subway GTFS-Realtime feeds: polls 8 protobuf feeds every ~30 s, computes per-stop headway residuals, and scores them with an online model that retrains in place and needs zero labels.

**[Live demo](https://stelioszach.com/demos/mta-scan/)**

[![CI](https://github.com/stelioszach03/NYC-Subway-Anomaly-Detection/actions/workflows/ci.yml/badge.svg)](https://github.com/stelioszach03/NYC-Subway-Anomaly-Detection/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-f59e0b?style=flat-square)](LICENSE)

## Results

Replay evaluation against three heuristic baselines. The point is the trade-off, not a win: the online model finds all three incidents with the longest lead time and pays the highest false-alarm rate.

| Method | FA rate | MRR | p@20 | r@20 | Incidents | Avg lead time | Evidence |
|---|---:|---:|---:|---:|---:|---:|---|
| Online model (River) | 0.030 | 0.199 | 0.80 | 1.000 | 3 / 3 | 6.67 min | [`metrics.json`](docs/generated/replay/metrics.json) |
| z-score baseline | 0.010 | 0.128 | 0.50 | 0.625 | 3 / 3 | 5.00 min | same |
| EWMA baseline | 0.005 | 0.181 | 0.50 | 0.625 | 3 / 3 | 2.50 min | same |
| Fixed-threshold baseline | 0.000 | 0.184 | 0.50 | 0.625 | 1 / 3 | 0.00 min | same |

**Read the dataset size before the numbers.** [`sample_subway_headways.csv`](evaluation/data/sample_subway_headways.csv) is 216 rows, 16 positives, 3 routes, 6 stops, 3 hand-labelled incidents, threshold 0.6. That is a sanity evaluation, not a benchmark. The interesting part is that the fixed-threshold rule has a perfect false-alarm rate and still misses two of three incidents.

## Run

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

PYTHONPATH=. pytest -q                                  # 11 passed, 4 skipped in 2.5 s
PYTHONPATH=. python scripts/run_replay_eval.py \
  --input evaluation/data/sample_subway_headways.csv --out-dir /tmp/replay
```

The replay output is byte-identical to the committed `docs/generated/replay/metrics.json` — verified by diff. It was not, until the categorical hash features were moved off Python's `hash()`, which CPython randomizes per process: the evaluation gave different p@k on every run, and a reloaded checkpoint was scoring a different feature space than it was trained on. It now uses `blake2b`, pinned by `tests/test_feature_hash_stability_unit.py` across three `PYTHONHASHSEED` values.

The full stack needs Docker: `docker compose up -d --build db api worker trainer dl_shadow ui` brings up TimescaleDB, the GTFS collector, the River trainer, a PyTorch DAE shadow model, FastAPI and a Next.js UI.

## Limitations

- **216 rows and 3 incidents.** Point estimates on 16 positives are noisy and no confidence intervals are computed. Nothing here supports a claim about detection quality at scale.
- The three incidents are representative scenarios hand-labelled by me, not official MTA incident annotations.
- The online model is tuned for responsiveness on a streaming feed, not offline accuracy — hence the highest false-alarm rate of the four methods.
- A headway anomaly is not a root cause; the reason strings are factor attributions.
- No static GTFS data is committed, so `/api/stops` and the map layers are empty until the static feed is downloaded.
- PyTorch is installed only inside `docker/Dockerfile.worker`; the DAE shadow model does not run in a plain local venv.
- Integration tests are skipped by default — they need a live Postgres and network access to the MTA endpoints.

## License

MIT — see [LICENSE](LICENSE).
