# Temporal summary interface v1

The offline worker writes `/var/lib/mta-temporal/public/summary.json` atomically with mode 0644; this dedicated public subdirectory is 0755. The state parent stays 0700 and feature/model/evidence files remain private under the worker's 0077 umask. The existing live adapter should receive only a read-only bind of `/var/lib/private/mta-temporal/public` at `/run/mta-temporal-public`, then read `/run/mta-temporal-public/summary.json`. It must not mount the private database directory, launch the worker, parse raw protobuf or train a model during an HTTP request.

The temporal unit uses the same `DynamicUser=yes` / `User=mta-history` identity as the active collector, and declares only its own `StateDirectory=mta-temporal`. An explicit read-only bind from `/var/lib/private/mta-history` to `/run/mta-temporal-source` bypasses the otherwise untraversable `/var/lib/private` parent while preserving the collector-owned directory's Unix permissions. The source remains read-only inside the temporal namespace. An inactive/misowned collector state fails closed; do not chmod the raw archive for web access.

The schema value is `mta-temporal-evaluation-v1`. A clearly labeled collecting-state fixture is [fixtures/temporal-collecting.json](fixtures/temporal-collecting.json). It is a wrapper containing `fixture_only` and the example `summary`; it must not be deployed as live evidence.

| Field | Meaning and display rule |
|---|---|
| `generated_ts`, `generated_at_utc` | Actual summary publication time. |
| `valid_until_ts` | Forecast expiration. Independently hide forecasts when current time exceeds it, even if the worker last reported ready. |
| `feature_cutoff_ts` | End of the last completed five-minute input window. |
| `evaluation_cutoff_ts` | Cutoff of the latest hourly train/validation/test analysis; deliberately separate from refreshed forecast origins. |
| `target_name` | Always **future feed-predicted arrival-spacing proxy**. |
| `is_observed_train_headway` | Always false. Never relabel this target as observed headway, waiting time or train passage. |
| `incident_evaluation_available` | Always false for this pipeline; no incident labels are synthesized. |
| `readiness.status` | `collecting`, `short_window_feasibility`, `ready`, `temporarily_unavailable`, or `error`. |
| `readiness.public_forecasts_ready` | False means the forecasts array must be empty. At least 14 days, comparable platform coverage, fresh collection and valid held-out evaluation are required. |
| `readiness.reasons` | Human-readable reasons for withholding a public forecast. |
| `coverage` | Retained feature-window span, expected slots, fresh coverage and evaluated stable groups; may be absent/null before the first feature. |
| `feeds` | Per-feed latest poll status, receipt/source ages and receipt timestamp. No raw trip identifiers or server paths. |
| `metrics` | Validation/test metrics for 900/1800 seconds. Every algorithm includes measured n, eligible n and coverage. MAE/RMSE/bias are null when unmeasured. Short-window values are feasibility evidence only. |
| `forecasts` | Fresh route/direction-specific proxy forecasts only when all applicable gates pass. Each includes horizon, origin/target timestamps, algorithm, stable-cohort count/hash and validation/test error. |
| `pipeline` | Pending and ingested export-day counts plus derived feature bytes; no database paths. |
| `artifact_id` | Identifier of immutable private evaluation evidence, not a URL and not a file path to concatenate from user input. |
| `limitations` | Scope statements that accompany results. |
| `error_category` | Optional allowlisted Python exception class for a failed worker; no raw exception text or internal paths. |

Algorithm labels are `persistence`, `seasonal_24h` and `online_linear`. `online_linear` is selected only when full-coverage validation MAE improves on persistence by at least 5%; a seasonal baseline must have the same eligible validation coverage. The test partition never fits or chooses a model. Display test error even when an alternative is worse there; do not turn validation selection into an unqualified superiority claim.

Direction values such as `platform:N` and `platform:S` identify the documented versioned NYCT platform-suffix convention. They are not inferred geographic headings. Otherwise explicit GTFS direction IDs are `gtfs:0` / `gtfs:1`, and absent direction remains `unknown`.

Client behavior should fail closed: absent/invalid/unknown-schema/stale JSON shows collection or monitoring unavailable and no forecasts. A ready summary with expired origins must not keep stale predictions on the map. Expose only the safe fields above, and render labels as plain text.
