# Model Card

## Model Summary

The production-facing scorer is a hybrid online anomaly model for subway headway disruption detection.

Core components:
- River `PARegressor` for online headway prediction
- River `HalfSpaceTrees` for unsupervised anomaly signal
- ADWIN drift monitor for reset-on-shift behavior
- hybrid anomaly score combining residual calibration with contextual deviation features

## Prediction Target

Target:
- `headway_sec` at a `(route_id, stop_id, observed_ts)` observation

Output:
- `predicted_headway_sec`
- `residual`
- `anomaly_score` in `[0, 1]`

## Features

The fast-path model now uses richer context including:

- hour of day
- day of week
- weekend and rush-hour indicators
- previous headways
- rolling mean / std / quantiles
- station-local median / MAD deviation
- route-direction encoding
- feed staleness / delay features
- optional weather and service-alert features

## Intended Use

Intended for:
- operator-facing anomaly triage
- route-stop hotspot discovery
- incident replay and debugging
- portfolio demonstration of online ML systems engineering

Not intended for:
- authoritative dispatch decisions without human review
- contractual SLA enforcement
- causal diagnosis on its own

## Training / Update Regime

The model is trained online as new scored observations arrive. It is not a heavyweight offline batch trainer. That design choice is deliberate because the project is optimized for low-latency operational adaptation.

## Evaluation

See [EVALUATION.md](./EVALUATION.md). The repository includes a replay runner and baseline comparisons to make behavior inspectable and reproducible.

## Risks

- cold-start behavior depends on limited early context
- headway anomalies are proxies for incidents, not ground-truth incident labels
- concept drift can still produce false positives during schedule shifts or feed quirks
