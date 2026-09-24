# Temporal worker deployment receipt

**Verified September 24, 2026, around 21:57 UTC.** The autonomous temporal worker and read-only history pane are deployed. Open the [public history pane](https://stelioszach.com/demos/mta-scan/#temporalPanel) or its [validated summary API](https://stelioszach.com/demos/mta-scan/api/temporal).

The [sanitized dated snapshot](../artifacts/deployment/mta-temporal-2026-09-24T215701Z.json) contains actual service/timer observations, aggregate coverage, source hashes, API metrics and preservation/access checks. It contains no raw database, protobuf payload, individual trip/platform identifiers, host address, OS identity or server filesystem path. Earlier collection reports remain unchanged.

## Observed operation

| Component | Observed state |
|---|---|
| Independent history collector | Active/running; last start 21:41:39 UTC and no automatic restarts reported since that start |
| Temporal worker | Last scheduled run finished successfully; inactive between oneshot invocations is expected |
| Temporal timer | Enabled and waiting; five-minute schedule |
| Public MTA service | Active/running; temporal endpoint returned HTTP 200 with four measured validation/test rows |
| Daily export and hourly retry timers | Enabled and waiting |
| Completed UTC-day Parquet | **Zero at this cutoff.** Collection was still in its first UTC day; a successful earlier empty export is not a completed-day artifact |

The current evaluation covers **256 selected five-minute windows, 21 hours 15 minutes and 39 evaluable route/direction groups**. The feature and evaluation cutoff timestamps are separate in the snapshot because models are evaluated hourly while inputs/status refresh every five minutes. Complete freshness of selected feature windows does not mean every poll succeeded: the archive contained **10,352 polls, including one retained decode error**.

The API reports **short-window feasibility** and publishes **zero forecasts**. The 14-day history and comparable-coverage gates have not passed. Metrics measure future feed-predicted arrival-spacing proxies, not observed train headways, passenger waiting times or incident detection. No longitudinal or operational-accuracy claim follows from this deployment.

## Source and isolation checks

- Six critical worker/evaluation/export/time-source files matched commit [`99260d8`](https://github.com/stelioszach03/NYC-Subway-Anomaly-Detection/commit/99260d8ddf289a20c3436746faf4ed3004879bf2). The cached evaluation's source manifest matched the installed files. The [commit's CI run passed](https://github.com/stelioszach03/NYC-Subway-Anomaly-Detection/actions/runs/36062813681).
- Four public service/UI files matched portfolio commit [`dff430d`](https://github.com/stelioszach03/stelioszach-portfolio/commit/dff430dc4aef55776281db04107ec78d9fc282c2).
- Checks entered the actual public service's mount namespace and switched to its process identity. Reading the dedicated sanitized summary was allowed; a write-open attempt was denied and its bind mount was read-only. Access to the private history and temporal databases was denied. No contents of those databases were read under the public identity and no write/truncate operation was performed.
- Comparing the pre-deployment backup with the retained source archive found **all 10,224 existing poll rows and 10,224 compressed snapshot payloads unchanged**. Both earlier public coverage-audit hashes also reconciled exactly.
- **128 new polls** had the explicit `response_available_v2` marker. Their stored observed/completion timestamps matched and did not precede request start. Legacy rows were not rewritten to conceal the earlier request-start semantics.

The temporal worker has no network, a 25% CPU quota, a 512 MiB memory limit and a 21-minute oneshot ceiling. Repeated timer ticks do not spawn another instance while the same oneshot unit is active; a separate file lock also rejects overlapping manual invocations. These controls constrain resource use; this dated receipt is not a promise of indefinite uptime or data retention.

Rollback backups were present for both the worker and public-view deployments. This verification was read-only: no restarts, configuration edits, new model evaluations or paid calls were performed. The next operational evidence boundary is an actual completed-day Parquet export; the next public forecasting boundary remains the measured history/readiness gate.
