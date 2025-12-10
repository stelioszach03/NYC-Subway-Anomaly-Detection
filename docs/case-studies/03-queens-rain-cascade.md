# Case Study 03: Rain-Impacted Dwell Times Cascade On The Queens Corridor

## What Happened

A representative weather-impacted scenario on the `7` corridor created slower boarding, longer dwell times, and a corridor-wide headway swell around `726N / Queensboro Plaza`.

## When

Replay window:
- `2026-02-05T13:00:00+00:00` to `2026-02-05T13:50:00+00:00`

## What The Model Saw

- higher precipitation context was present in the replay input
- rolling and station-local baselines both drifted upward, but the event still broke above them
- the anomaly rank stayed elevated across multiple consecutive replay steps

## Why It Was Flagged

Top contributing factors:
- weather pressure
- station baseline deviation
- rolling z-score jump

## What Baselines Did

- z-score catches the peak but is less expressive about contextual weather pressure
- the threshold rule is conservative and misses more of the early build-up

## Plot Reference

- `docs/generated/replay/plots/queens-rain-cascade.svg`

## Caveats

Weather here is an optional feature hook demonstrated through replay data, not yet a live external integration by default.
