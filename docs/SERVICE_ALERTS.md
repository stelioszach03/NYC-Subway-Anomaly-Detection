# Official subway service-alert context

This independent collector polls the [official MTA subway alerts feed](https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts) once per minute. The [MTA developer page](https://www.mta.info/developers) and [Mercury alert specification](https://www.mta.info/document/90881) document the source and alert semantics. It does not alter the existing trip-feed collector, raw history, temporal features or learned model.

## Data and timing

The archive keeps exact compressed protobuf snapshots, their SHA-256 hashes, source timestamps, response-availability timestamps, failed polls and normalized alert revisions. Repeated identical revisions preserve first/last observation times. Current visibility uses the alert's active periods (including open-ended intervals); future planned work is archived but not presented as active. A changed headline, description, route set or active period creates a new revision.

Plain-text English is preferred over the `en-html` variant. The public summary truncates long descriptions explicitly, publishes at most 100 active messages, and stays below 256 KiB including JSON escaping. The raw archive retains the original source. Route selectors describe the alert's published scope; they do not establish which station or direction experienced an incident.

Publication requires a source timestamp no older than ten minutes (the [GTFS service-alert freshness recommendation](https://gtfs.org/documentation/realtime/realtime-best-practices/)) and no more than 30 seconds in the future. The HTTP adapter independently checks receipt freshness (three minutes), source age, active periods, expiration, schema and duplicate identities. The browser also withdraws expired messages without waiting for another successful request. Collection or parse failure publishes an unavailable state, rather than stale messages labelled current.

## Interpretation

These are official service messages, not validated incident ground truth and not model predictions. An alert may be delayed, revised, broad in geographic scope or related to planned work. The new archive starts at its first actual receipt; it does not backfill earlier incidents or relabel the constructed replay. A future incident evaluation needs a frozen matching/label protocol and prospective held-out data. Alert absence does not certify normal service.

## Resource bounds

The SQLite archive uses a 256 MiB page cap, age/count retention (raw polls: seven days / 10,080 rows; revisions: 30 days / 10,000 rows), and earlier pruning at 85% of the byte cap. The first limiting policy wins; the API reports actual retained receipt times and counts. SQLite's temporary rollback journal can use additional space during a transaction. A 2 GiB filesystem reserve is required.

Each fetch is limited to 4 MiB with network timeouts; the service has a 45-second runtime limit, 128 MiB memory limit and 20% CPU quota. A nonblocking file lock prevents overlapping writers. No model API, GPU or paid service is called. Only the 0755 `public/` directory and its 0644 summary are mounted read-only into the public demo namespace. The database and raw payloads remain private to the collector identity.

## Deployment

Install `worker/service_alerts.py` beside the existing history worker and use its `requirements.history.txt` environment. Install `infra/mta-service-alerts.service` and `.timer`, reload systemd, start the service once and inspect the resulting public summary before enabling the timer.

The demo requires `service_alerts_view.py`, the `/api/service-alerts` route, `static/service-alerts.js`, the corresponding existing-style panel and this drop-in:

```ini
[Service]
BindReadOnlyPaths=/var/lib/private/mta-service-alerts/public:/run/mta-alerts-public
Environment=MTASCAN_SERVICE_ALERTS=/run/mta-alerts-public/summary.json
```

Start the collector before restarting the demo, so the bind source exists. Verify the public endpoint and one subsequent scheduled collection. Rollback restores the prior demo files/drop-in and stops/disables the new timer; retain the alert archive for audit. Existing trip collection and temporal evaluation do not depend on this service.

## Offline validation

```sh
PYTHONPATH=. python -m pytest tests/test_service_alerts_unit.py
```

The tests cover exact snapshot recovery, revision deduplication, receipt clocks, future periods, stale/future feed timestamps, failed fetches, malformed/oversized payloads, unsupported incremental updates, retention and public byte/permission bounds. The deployed adapter has separate API-contract and DOM interaction tests for expiry, route filtering, escaping and preserved expanded messages.
