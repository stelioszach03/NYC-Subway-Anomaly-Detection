# Data Card

## Data Sources

Primary live source:
- MTA Subway GTFS-Realtime feeds (TripUpdates / VehiclePositions)

Derived signals:
- route-stop headway observations
- observed timestamps
- optional event timestamps from GTFS-RT
- optional external weather and service-alert context

## Sample Replay Dataset

Repository dataset:
- `evaluation/data/sample_subway_headways.csv`

This file is a clearly labeled representative replay dataset created for:
- local reproducibility
- CI and smoke checks
- replay UI demos
- documentation and case studies

It is not a claim of official labeled subway incident truth.

## Schema Highlights

Key columns:
- `observed_ts`
- `event_ts`
- `route_id`
- `stop_id`
- `stop_name`
- `headway_sec`
- `label`
- `incident_id`
- `incident_title`
- `precipitation_mm`
- `service_alert_active`

## Replace With Real Historical Data

The [raw collector](HISTORICAL_COLLECTION.md) retains original protobuf bodies
and a poll manifest with receipt/source timestamps, response hashes, freshness
and errors. Optional fields stay optional; raw ETA revisions are not observed
passages. Its bounded archive is separate from this constructed replay fixture.
The optional daily Parquet export preserves nullable standard trip/stop/vehicle
fields and alerts, UTC poll/source timestamps, freshness and poll failures.
Atomic per-day manifests record hashes, counts and actual coverage. Months of
data have not been created retroactively; an independently evaluated label
pipeline remains future work.

To swap in retained observations:

1. export route-stop observations to CSV with the same core columns,
2. preserve timestamp ordering,
3. add labels if available, or incident windows / weak labels if not,
4. run `scripts/run_replay_eval.py --input <your_csv>`.

## Caveats

- GTFS-RT is an operational feed, not a curated ML benchmark.
- Missing trips, stale timestamps, and feed quirks are part of the real problem.
- Labels are usually sparse, delayed, or indirect.
