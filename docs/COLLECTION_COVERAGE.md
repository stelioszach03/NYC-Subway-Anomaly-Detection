# Observed collection coverage

These are dated, read-only audits of collection quality and separately identified
temporal proxy evaluations. They are not incident-detection results. Earlier
snapshots are preserved unchanged.

Timestamp clarification: those legacy audits used `observed_ts`, which the
original collector recorded at request start. Their numerical values and
artifacts are preserved; older references to receipt time should be read with
that limitation. The corrected collector and [availability-aware temporal
protocol](TEMPORAL_EVALUATION.md) distinguish response availability explicitly.

## Current audit — 7 November 2026

The [November 7 audit](../artifacts/collection/audit-2026-11-07.json) records **44 completed UTC-day exports**, from September 24 through November 6. All **44/44** Parquet files passed SHA-256 and metadata row-count checks against their immutable manifests. Together they contain 806,630,656 normalized snapshot rows in 6,403,335,601 bytes. Repeated predictions across snapshots are expected: these are not distinct train passages, people or incident labels.

The deployed temporal pipeline has ingested all 44 exports with zero pending days. Its rolling **28-day** evaluation contains **8,060 retained five-minute windows** out of 8,065 expected slots, **45 stable route/direction groups**, and **99.44% complete/fresh windows**. All eight feed groups were fresh at the snapshot. Readiness was `ready`, with 82 current group/horizon forecasts. Forecast counts and freshness are time-sensitive; the live adapter independently expires stale results.

Held-out test results at the frozen evaluation cutoff:

| Horizon | Paired rows | Persistence MAE | Online linear MAE | Validation-selected MAE |
| --- | ---: | ---: | ---: | ---: |
| 15 minutes | 69,331 | 146.33 s | 198.18 s | 146.31 s |
| 30 minutes | 69,132 | 166.04 s | 227.40 s | 165.46 s |

Persistence and the linear model use the same paired test rows. The 24-hour seasonal baseline has different coverage (97.75% / 97.88%) and must not be interpreted as a fully matched comparison. Validation chooses each group/horizon algorithm; the test data do not train or select it. The linear model is worse in aggregate here; the selected pipeline is close to persistence. No general model superiority is established.

**The collection-time gate has been met for the implemented proxy-forecast pipeline.** Collector, export and temporal evaluation services are operating successfully. This does not complete incident prediction: official event labels, an event-matching protocol and a prospective held-out incident evaluation are still needed for that separate claim. The present target remains future feed-predicted arrival spacing, not realized train headway or passenger waiting time.


## Earlier public snapshot — 9 October 2026, 17:45:47 UTC

The [archived public aggregate](../artifacts/collection/portfolio-review-2026-10-09.json)
records 15.69 days of retained evaluated history, 4,519 five-minute windows,
99.93% complete fresh windows and 44 stable route/direction groups. The live
history pane also reported 15 completed-day exports ingested, with none pending.
Public 15/30-minute proxy forecasts were ready at this snapshot; their ongoing
availability depends on freshness and coverage checks. Check the
[live history pane](https://stelioszach.com/demos/mta-scan/#temporalPanel)
for the current state. This dated audit is not an uptime guarantee.

Held-out MAE in seconds at that cutoff:

| Horizon | Persistence | 24-hour seasonal | Online linear | Validation-selected |
| --- | ---: | ---: | ---: | ---: |
| 15 min | 159.1 | 142.1 | 171.1 | 156.1 |
| 30 min | 175.9 | 142.1 | 190.4 | 170.6 |

The seasonal baseline has approximately 99.6% coverage; the other rows have
100%. These aggregate errors do not all use exactly the same sample. The
online model did not improve MAE over persistence at either horizon. Selection
uses validation only; no method was retuned or selected on these test results.
The target remains a future **feed-predicted arrival-spacing proxy**, not
observed train passages, waiting time or labelled transit incidents. This is a
public-summary audit, not an independent reconstruction of the private archive.
Earlier audits below remain unchanged.

## Earlier check — 24 September 2026, 11:39:28 UTC

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

The original completed-day and elapsed-history gates are now met, as shown in the November 7 audit. Additional elapsed time alone does not provide incident ground truth; incident-level validation still needs an explicit label protocol and a frozen prospective split.
