# Autonomous temporal evaluation

The offline pipeline implements bounded, chronological evaluation at **15 and 30 minutes** from the retained MTA feeds. Its named target is **future feed-predicted arrival-spacing proxy**. It does not manufacture observed train passages, passenger waiting times, incident labels or months of history. The [GTFS-RT reference](https://gtfs.org/documentation/realtime/reference/#message-stoptimeevent) describes stop-time events as estimates or actual times depending on source semantics; a future ETA alone is not an observed passage.

## Target and comparable platform cohorts

For each completed five-minute window, choose the latest available poll from each feed. Keep a failed latest poll as failed rather than replacing it with an earlier successful one. Source freshness is checked at the decision cutoff. Each eligible platform contributes the gap between the earliest two **distinct trip/service-date identities** with arrival predictions between the cutoff and one hour ahead. Duplicate revisions of the same trip do not become a second train. Missing route, platform, trip or service-date fields, skipped stops, canceled trips and missing/past/distant estimates are excluded with counts.

Keep direction separate. A stop ID ending in `N` or `S` uses the explicit versioned NYCT platform-suffix convention (`platform:N`, `platform:S`), not an inferred geographic heading. Otherwise retain an explicit GTFS direction as `gtfs:0` / `gtfs:1`; missing direction is `unknown`.

Per route/direction, select at most three platforms by **training-period availability only**, requiring at least 70% training-window coverage. The target is the median spacing for that fixed cohort in the future feed snapshot. Every evaluated origin and target must contain the entire cohort. Paired platform count, full-cohort coverage, cohort hash and changes in the broader source-platform membership are retained. This prevents comparing medians from different platform sets as if they were the same target. It does not prove the selected platforms represent every service pattern or station.

## Availability timestamps and backward compatibility

An audit found that the original collector recorded request-start time in `observed_ts`, although earlier documentation called it receipt time. Old rows and previous audit artifacts are preserved. The corrected collector marks new rows in `metadata_json` with `timestamp_semantics=response_available_v2`, original `poll_started_ts` and `response_available_ts`; `observed_ts` now records response availability. Source freshness is evaluated then.

The temporal reader treats the whole-second response timestamp plus one second as a conservative availability cutoff. Legacy rows use **request start + ceil(recorded latency / 1,000) + two seconds**, explicitly labeled `legacy_start_plus_latency_and_two_second_guard`. This is a conservative reconstruction of response availability, not a measured historical database-commit timestamp. Unknown latency/semantics stays unknown. A request that starts before a decision boundary but completes afterward cannot enter the earlier feature window.

New completed-day Parquet exports use **schema 2**, adding `poll_latency_ms`, `available_ts` and `availability_semantics`. Existing schema-1 exports remain immutable and can still pass integrity verification; they are never overwritten by the new exporter. If a legacy Parquet file lacks availability columns, the temporal worker records it as unusable for this evaluation instead of inventing timestamps. Any retained raw data can still supply the needed information.

Standalone per-day backfills deliberately omit the first five-minute UTC boundary window because a legacy request may have started in the preceding day. The continuous raw-tail path can preserve it. A rebuild from exports alone may therefore have explicit boundary gaps. Coverage denominators include those gaps; recovery does not promise byte-identical reconstruction of expired raw history.

## Chronological protocol

The current fixed configuration evaluates up to the last 28 days of retained features:

- Split elapsed time at 60% and 80% into training, validation and test.
- Leave a 30-minute gap after each boundary. Every origin's target must also remain inside its own partition. This is enforced for both 900- and 1,800-second horizons.
- Fit a small regularized linear residual model in chronological order using only training pairs whose future labels have matured by the training cutoff. Its seven features are current spacing, differences from 15/30/60-minute lags and daily UTC sine/cosine terms, plus intercept. The training pass is incremental SGD; validation/test observations never update weights.
- Compare persistence, an exact 24-hour-lag seasonal proxy, and the fitted linear model. Missing seasonal observations yield null metrics, not zero error.
- Select a production shadow algorithm **on validation only**. Persistence remains the reference. Another algorithm must have the same validation coverage and at least 5% lower validation MAE. The test partition never fits or selects a model; its measured error is still displayed if the validation-selected model performs worse there.

Report n, eligible n, coverage, MAE, RMSE and bias in seconds. Separate source groups and exact paired rows remain inspectable. Related windows/platforms are not independent observations, and this pipeline makes no confidence-interval, significance or general-superiority claim. These measurements concern the later feed proxy, not actual realized service or causal incident detection.

## Readiness and public forecasts

A minimum 12-hour span supports only **short-window feasibility**. A public forecast requires at least 14 days of retained coverage, at least 90% complete/fresh feed windows, adequate train/validation/test pairs, current collection and comparable stable-cohort coverage. At least two groups must have valid evaluations; each published group/horizon also needs 80% test-pair coverage and a fully present current cohort. Freshness or catch-up failures suppress forecasts. These thresholds are engineering gates, not guarantees of useful forecasting performance.

The worker refreshes features and the safe public summary every five minutes, but does the full fit/evaluation at most hourly. Between evaluations it refreshes inputs for the existing train-only models without fitting new labels. A model older than six hours is not used. Forecasts expire ten minutes after the input cutoff; the HTTP adapter must enforce expiration independently.

See [TEMPORAL_INTERFACE.md](TEMPORAL_INTERFACE.md) for the stable safe JSON contract. The public array is empty until readiness holds. Do not expose private feature databases, model weights, raw trip identifiers or source paths through that endpoint.

## Persistence, recovery and bounds

- Raw history remains independently bounded to seven days / 2 GiB; completed-day Parquet to 90 days / 10 GiB. Their existing retention policies are unchanged.
- The temporal store retains compact per-platform proxy values for up to **90 days / 512 MiB**. A byte-limit cleanup removes oldest derived windows, never source archive rows or Parquet. An explicit 2 GiB free-space reserve prevents writes. The actual retained span is measured; 90 days is not guaranteed.
- Verified completed-day exports are ingested once by date/hash. The worker backfills at most two new export days per invocation, then reads a bounded raw tail. Raw availability filtering uses measured latency, so already-expired raw history is not the only source for long-term evaluation.
- Window input hashes, derived hashes, schema and derivation-code identity prevent silent changes to completed features. A changed derivation requires a **new versioned temporal state directory**; retain the prior directory for audit. Do not remove the raw archive to perform this migration.
- A single worker lock prevents overlapping timer/manual executions. A duplicate invocation is skipped without overwriting live status. Transactions protect feature insertion; raw-tail and export checkpoints advance only after successful processing.
- Evaluation evidence is staged and atomically published under `runs/<cutoff>-<input hash>-<analysis hash>/`: evaluation JSON, compressed paired predictions and provenance hashes. Existing artifacts are verified on reuse. Only the worker's own generated evidence is rotated, at **48 reports / 256 MiB**. Repository reports and raw source files are outside this retention policy.
- Stale incomplete staging directories are removed under the exclusive worker lock. Corrupt existing exports/evidence are reported, not silently replaced. A safe error summary suppresses forecasts; detailed exceptions remain in private service logs.
- The process has a 20-minute internal deadline; systemd adds a 21-minute limit, 25% CPU quota, 384 MiB memory-high / 512 MiB hard limit, low scheduling priority and no network access. It uses no GPU or paid model API.

The optional `mta-history-export-retry.timer` activates the existing export service hourly after its daily schedule. It retries failed completed-day exports automatically; immutable-file validation and the existing export lock make successful reruns idempotent. The source collector and live demo remain separate services.

## Deployment and rollback

Review and stage the following source files in the existing root-owned `/srv/mta-history` tree: `worker/__init__.py`, `worker/history.py`, `worker/history_time.py`, `worker/history_export.py`, `worker/temporal_features.py`, `worker/temporal_evaluation.py`, `evaluation/__init__.py`, and `evaluation/temporal.py`. Install `requirements.temporal.txt` in that service's venv. The corrected collector semantics require restarting only the independent history collector after review; the live map does not need a restart for collection changes.

The temporal service uses the shared `mta-history` DynamicUser identity. The raw source directory is explicitly read-only-bound at `/run/mta-temporal-source`; its Unix ownership stays with that identity. The private temporal state directory is 0700. Only its `public/` child is 0755 and the atomic `summary.json` is 0644. Bind only `/var/lib/private/mta-temporal/public` into the live adapter namespace, as documented in the interface, never the state/database parent.

```sh
# After reviewing/installing the code and requirements:
sudo cp infra/mta-temporal-evaluation.service infra/mta-temporal-evaluation.timer /etc/systemd/system/
sudo cp infra/mta-history-export-retry.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mta-temporal-evaluation.timer mta-history-export-retry.timer
sudo systemctl start mta-temporal-evaluation.service
sudo systemctl status mta-temporal-evaluation.service --no-pager
sudo systemctl list-timers 'mta-*' --no-pager
```

Inspect the safe summary and private provenance, then verify a second invocation is idempotent and the live site still responds. A missing collector/incorrect source ownership fails closed; do not make raw history world-readable to solve permissions. Rollback disables the two new timers and stops the temporal worker; preserve both source history and temporal state/evidence. The original daily exporter and collector can continue independently.

## Verification

Offline tests cover future-label boundaries at both horizons, fixed-cohort membership, missing seasonal values, validation-only selection, unchanged weights after test-target changes, request-start/response-time separation, raw/Parquet equivalence, schema-1 preservation, export-backed recovery after raw retention, transactions, locks, artifact corruption, safe public permissions and idempotence. The dedicated history CI job installs the optional Parquet dependencies and runs these tests. Synthetic fixtures are not evidence of model quality.

A development feasibility check on a read-only snapshot of **20 hours 40 minutes** of actual retained history produced 249 completed feature windows and 39 evaluable route/direction cohorts. It was explicitly a short-window check: the seasonal baseline was unmeasured and public forecasts stayed empty. The source archive, preliminary artifact and corrected availability-aware artifact are preserved privately. This check is not a longitudinal benchmark or a deployment receipt; future product processing runs on the VPS.
