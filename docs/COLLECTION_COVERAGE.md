# Initial observed collection coverage

This is a real, read-only audit of the new collection archive at
**2026-09-24 02:15:38 UTC**, not a forecasting or incident-detection result.

The [machine-readable report](../artifacts/collection/initial-2026-09-24.json)
contains **896 poll records**, 112 for each of the eight configured feed groups.
Every recorded poll in this initial window was successfully parsed and fresh at
receipt. Maximum inter-poll intervals ranged from 60 to 62 seconds; none exceeded
the declared 120-second gap threshold. This covers only the initial approximately
111-minute interval, not weeks of operation or guaranteed future availability.

Freshness denominators include failed polls; missing source timestamps stay null.
The report retains first/last receipt times, status counts, interval statistics,
analysis-source hash and canonical-input-row hash. It does not infer unrecorded
requests or call feed estimates actual train passages. Eight fresh feed groups
also do not establish complete station, route or service-alert coverage.

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
