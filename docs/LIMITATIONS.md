# Limitations

This repository is intentionally production-flavored, but it still has important limitations.

## Data and Labels

- True incident labels are limited.
- Replay evaluation currently relies on representative labeled scenarios rather than official incident archives.
- Headway anomalies do not uniquely identify root cause.

## Modeling

- The online model is optimized for responsiveness, not maximum offline benchmark accuracy.
- Cold-start behavior can still be noisy.
- False positives remain possible during schedule changes, feed resets, or unusual but acceptable service patterns.

## UI and Operations

- The live UI is an operator-style triage surface, not a dispatch console.
- Explanations are factor attributions, not causal proofs.
- Replay artifacts are only as strong as the underlying retained observations and labels.

## What To Do Next

Natural next steps for a stronger real deployment:
- store longer historical windows for evaluation on real incidents,
- ingest official service alerts and weather automatically,
- add route topology context and transfer impact propagation,
- collect human feedback labels from triage decisions,
- compare against a stronger offline sequence model while preserving the fast online path.
