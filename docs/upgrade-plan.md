# Upgrade Plan

## Current State

The repository already has a credible end-to-end architecture:

- `worker/collector.py` ingests MTA GTFS-RT trip updates and writes headway observations.
- `worker/ml_online.py` performs fast online scoring with a River regressor, Half-Space Trees, and ADWIN drift monitoring.
- `api/app` exposes live summary, anomaly, heatmap, route, stop, and model telemetry endpoints.
- `ui/pages/map.tsx` provides a live operator-style command center over the API.
- Docker, tests, and smoke scripts already exist.

## Gaps To Address

1. Feature context is still thin.
   - The online scoring path only uses `hour`, `route_hash`, and `stop_hash`.
   - There is no explicit rush-hour context, day-of-week signal, rolling headway context, station-local baseline deviation, or feed freshness signal.

2. The project does not yet prove model quality.
   - There is no reproducible historical replay pipeline.
   - There are no baseline comparisons or evaluation artifacts.

3. The UI is strong for live monitoring but weak for storytelling.
   - There is no incident replay flow, scrubber, explanation panel, or baseline comparison view.

4. Documentation is not yet flagship-level.
   - `docs/` is empty.
   - There are no case studies, model/data cards, or evaluation docs.

## Implementation Plan

### 1. Modular feature engineering
- Extend `worker/features.py` into reusable feature builders.
- Add richer contextual features while preserving the current fast online inference path.
- Include tests for deterministic feature behavior on small samples.

### 2. Replay evaluation package
- Add an `evaluation/` module for replay data loading, baseline scoring, ranking metrics, and artifact generation.
- Add a sample replay dataset for reproducible local evaluation.
- Add a script entry point under `scripts/` to run replay evaluation and emit JSON/CSV summaries.

### 3. Replay-aware API surface
- Add API endpoints that expose replay summary, timeline points, and incident details.
- Keep these endpoints read-only and based on generated artifacts or sample data.

### 4. Replay command center UI
- Add a replay page/view to the existing Next.js app.
- Include a time scrubber, score-over-time visualization, top affected routes/stations, model vs baseline comparison, and a concise explanation panel.
- Preserve the existing live map page.

### 5. Case studies and repo polish
- Add `docs/case-studies/` with at least three concrete scenarios.
- Upgrade the README to explain the architecture, why the project matters, how replay evaluation works, and how to run everything locally.
- Add `MODEL_CARD`, `DATA_CARD`, and `LIMITATIONS` docs.

### 6. Tests and verification
- Add unit tests for feature engineering and replay evaluation utilities.
- Add API tests for replay endpoints.
- Add a small UI contract test where practical without making the suite brittle.

## Non-Goals

- Replacing the online River-based system with a heavier offline training stack.
- Rewriting the frontend or backend from scratch.
- Adding external services that make local development materially harder.

## Success Criteria

By the end of this upgrade, the repository should:

- keep the current live system working,
- expose richer model context,
- include a reproducible replay evaluation with baselines and metrics,
- provide a replay-oriented operator experience in the UI,
- and read like a polished flagship ML systems project on GitHub.
