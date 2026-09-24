# Observed collection coverage

These are dated, read-only audits of the collection archive, not forecasting or
incident-detection results. Earlier snapshots are preserved unchanged.

Timestamp clarification: those legacy audits used `observed_ts`, which the
original collector recorded at request start. Their numerical values and
artifacts are preserved; older references to receipt time should be read with
that limitation. The corrected collector and [availability-aware temporal
protocol](TEMPORAL_EVALUATION.md) distinguish response availability explicitly.

## Latest check — 24 September 2026, 11:39:28 UTC

The [continuation report](../artifacts/collection/continuation-2026-09-24T113928Z.json)
contains **5,408 poll records**, **676 per feed** across all eight configured feed
groups. The first-to-last recorded receipt span is **11 hours 15 minutes** for
each feed. Every retained poll was successfully parsed and fresh at receipt;
there were no missing source timestamps. Latest receipt ages at the cutoff were
16–18 seconds. Maximum inter-poll intervals ranged from 60 to 63 seconds, with
**zero gaps over the declared 120-second threshold** and no trailing gap over
that threshold.

Compared with the initial snapshot, this adds **4,512 recorded polls** (564 per
feed) over 9 hours 23 minutes 50 seconds between audit cutoffs. These are feed
polls, not observed train passages or incident labels.

The collector was running with zero recorded restarts. The daily export timer
was active and waiting, with its next scheduled run observed as
**2026-09-25 00:16:24 UTC**. At this check there were **zero completed UTC-day
Parquet exports** and zero Parquet bytes: collection was still within its first
partial UTC day. An active timer does not establish that an export completed.

The artifact retains the collection-report schema and adds separately labeled,
sanitized operational observations, comparison counts and the private receipt's
hash. It contains no raw feed payloads, host addresses or server paths. No
collector deployment, restart or configuration change was part of this check.

## Initial check — 24 September 2026, 02:15:38 UTC

The preserved [initial report](../artifacts/collection/initial-2026-09-24.json)
contains **896 poll records**, 112 per feed, covering approximately 111 minutes.
Every recorded poll in that window was successfully parsed and fresh at receipt.
Maximum inter-poll intervals ranged from 60 to 62 seconds; none exceeded the
120-second threshold.

## Interpretation

Freshness denominators include failed polls; missing source timestamps stay null.
The reports retain first/last receipt times, status counts, interval statistics,
analysis-source hashes and canonical-input-row hashes. They do not infer
unrecorded requests or establish weeks of operation or guaranteed future uptime.
Eight fresh feed groups also do not establish complete station, route or
service-alert coverage.

## Reproduce against a retained archive

```sh
python -m worker.history_quality \
  --database /path/to/history.sqlite3 \
  --output /new/path/coverage.json
```

The command opens SQLite in read-only mode with a consistent read transaction and
creates a new artifact without overwriting an old report. A later cutoff or raw
retention pruning changes the input hash; the public aggregate alone cannot
reconstruct the original raw feed bodies. Source data remain subject to MTA terms.
The synthetic unit tests validate the calculation, not transit-model performance.

The next data gate is a real completed UTC-day Parquet export and its coverage
manifest. Chronological model evaluation still requires elapsed collection time,
an explicit label protocol and a frozen temporal split.
