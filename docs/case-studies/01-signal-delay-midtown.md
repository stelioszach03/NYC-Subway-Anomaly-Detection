# Case Study 01: Signal Delay Cascades Into a Midtown Headway Gap

## What Happened

A representative northbound signal hold created a widening headway gap around `A15N / 125 St`, followed by delayed recovery rather than an immediate snap-back.

## When

Replay window:
- `2026-02-05T11:45:00+00:00` to `2026-02-05T12:30:00+00:00`

## What The Model Saw

- headway jumped well above the recent local median
- rolling z-score and station-local deviation both climbed sharply
- service-alert context was active during the event window

## Why It Was Flagged

Top contributing factors:
- station baseline deviation
- rolling z-score jump
- service alert context

## What Baselines Did

- z-score and EWMA both caught the event, but with weaker rank quality over the full replay
- the fixed threshold rule only catches the most extreme part of the gap

## Plot Reference

- `docs/generated/replay/plots/signal-delay-midtown.svg`

## Caveats

This is a representative replay scenario built for reproducibility, not an official MTA incident annotation set.
