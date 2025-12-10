# Replay Evaluation

This project now includes a reproducible replay evaluation flow so the anomaly stack can be judged on evidence, not only on architecture.

## What Gets Replayed

The replay runner consumes timestamped route-stop observations in chronological order and feeds them through the same online scoring path used by the live system:

1. build enriched temporal and operational features,
2. score the observation with the River online model,
3. update the online state,
4. compare the model against transparent baselines,
5. emit artifacts for the API, UI, and documentation.

Default dataset:
- `evaluation/data/sample_subway_headways.csv`

This sample is intentionally small and clearly labeled as a representative replay dataset. It is suitable for local runs, demos, CI checks, and recruiter walkthroughs. Replace it with a larger historical export to evaluate on real retained observations.

## Baselines

The replay pipeline compares the online model to three simple baselines:

- `zscore_baseline`: positive deviation over the recent rolling mean and rolling std.
- `ewma_baseline`: one-step EWMA forecast error.
- `threshold_baseline`: fixed rule over station-local median and upper quantile.

These baselines matter because they answer the obvious reviewer question: “is the ML model actually better than a simple heuristic?”

## Metrics

The evaluation emits:

- `precision@k`
- `recall@k`
- `false_alarm_rate`
- `incident_detection_rate`
- `average_lead_time_min`
- `average_time_to_detect_min`
- `mean_reciprocal_rank`

For the representative replay bundle committed in this repository, the online model currently detects all three replay incidents and achieves stronger `recall@20` than the simple baselines.

## Commands

Run the default replay evaluation:

```bash
PYTHONPATH=. python scripts/run_replay_eval.py \
  --input evaluation/data/sample_subway_headways.csv \
  --out-dir docs/generated/replay
```

## Output Artifacts

The script generates:

- `docs/generated/replay/summary.json`
- `docs/generated/replay/metrics.json`
- `docs/generated/replay/events.csv`
- `docs/generated/replay/timeline.json`
- `docs/generated/replay/incidents.json`
- `docs/generated/replay/incidents/*.json`
- `docs/generated/replay/plots/*.svg`

These artifacts are also what power the replay API and the replay UI page.

## Methodology Notes

- The online model is replayed sequentially and statefully to match the live fast-path behavior.
- The sample dataset uses representative labels and scenarios rather than official incident annotations.
- This is useful as engineering evidence and product storytelling, not as a claim of scientific benchmark leadership.
