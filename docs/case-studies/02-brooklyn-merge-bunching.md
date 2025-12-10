# Case Study 02: Brooklyn Merge Conflict Triggers Bunching At Bergen St

## What Happened

A representative merge conflict on the `F` corridor produced one long headway gap and stale updates around `F20N / Bergen St`, followed by bunching behavior.

## When

Replay window:
- `2026-02-05T12:30:00+00:00` to `2026-02-05T13:15:00+00:00`

## What The Model Saw

- headway inflated above the rolling upper quantile
- stale feed delay became part of the context
- station-local deviation stayed elevated even when the raw gap started to compress

## Why It Was Flagged

Top contributing factors:
- service alert context
- station baseline deviation
- rolling z-score jump

## What Baselines Did

- the EWMA baseline is competitive here because the shift is abrupt
- the threshold rule misses more of the pre-incident ramp-up

## Plot Reference

- `docs/generated/replay/plots/brooklyn-merge-bunching.svg`

## Caveats

This scenario is representative and intentionally simple enough to run locally.
