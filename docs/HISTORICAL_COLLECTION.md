# Raw historical collection and versioned exports

The SQLite layout remains schema 1. New Parquet exports are schema 2 and include
explicit input-availability fields; existing schema-1 exports remain immutable.
An audit identified that legacy `observed_ts` values recorded request start,
not response receipt. Old rows/audits are preserved. New collector rows mark
`response_available_v2` and retain both start and completion times in metadata.
The [temporal protocol](TEMPORAL_EVALUATION.md) describes conservative treatment
of legacy timings and the resulting forecasting-availability limits.

`worker.history` is a separate, bounded archive worker for the eight public
subway GTFS-Realtime feeds. It requires neither the experimental Postgres stack
nor the live demo's model/SQLite store. Deploying it does not restart either.

This slice starts retaining real observations prospectively. It does **not**
backfill prior months, create incident labels or train forecasts,
or establish that an ETA change is a train passage. The public live map remains
a separate service.

## Initial deployment check

Collection was enabled on the portfolio VPS on **2026-09-24 UTC**. Its first
completed cycle recorded eight HTTP-200 snapshots, one from each configured feed,
with fresh source timestamps. The process and daily timer were enabled, and all
29 offline collection/export tests passed on that server. The first manual export
returned `[]`, correctly: no completed UTC day existed yet. This is a startup
receipt, not a claim of uninterrupted operation or months of retained data.

## What is recorded

Every attempted poll records its timestamp semantics, feed name, HTTP result, latency,
parse status, source header timestamp (nullable), feed age at receipt and
freshness (`fresh`, `stale`, `future`, `unknown`). HTTP success alone does not
mean fresh data. A source timestamp more than 180 seconds old is stale; more
than 60 seconds ahead is marked future. A missing timestamp remains unknown.

Each bounded HTTP 200 body is retained verbatim as deterministic gzip in the
SQLite archive, keyed by its SHA-256 hash. Identical bodies deduplicate while
all polls remain recorded. Unknown protobuf fields/MTA extensions are preserved
because the collector never serializes the parsed message back to disk.
Malformed bounded bodies are retained with `decode_error`; oversize bodies are
rejected and their failed poll remains recorded.

This preserves trip IDs, source service dates, stop-time arrival/departure
estimates, optional direction, vehicle fields and in-feed alerts **when the
source supplies them**. It does not infer missing vehicle coordinates or assert
that a separate service-alert feed has been collected. The official MTA
[developer page](https://www.mta.info/developers) documents custom subway and
service-alert extensions. Data-use terms remain separate from this repository's
MIT software license; no MTA endorsement or logo rights are implied.

## Run and inspect

```sh
python3.11 -m venv .venv-history
.venv-history/bin/python -m pip install -r requirements.history.txt
# Makes eight public MTA requests; writes only to the explicit state directory.
.venv-history/bin/python -m worker.history --state-dir var/history --once
# Read-only inspection, no collection request.
.venv-history/bin/python -m worker.history --state-dir var/history --status
# Continuous collection (Ctrl-C stops after the in-flight bounded request).
.venv-history/bin/python -m worker.history --state-dir var/history
```

The `--status` output includes the oldest/newest retained poll, poll and unique
snapshot counts, actual SQLite/WAL/SHM bytes, filesystem free bytes, per-feed
last poll age and **current** source age. A stopped collector is therefore
visible even if its last fetch succeeded. No status endpoint is exposed to the
internet by this worker.

## Resource policy

Defaults are a 60-second cycle target, seven days of retention, 150,000 poll
rows, a 2 GiB archive cap, a 2 GiB filesystem reserve, and a 4 MiB decoded HTTP
response cap. The effective retention is whichever limit is reached first;
seven complete days are **not guaranteed**. Measure actual compressed growth
before increasing retention. Do not copy an old headway-row size estimate to
this raw archive: these are different datasets.

Age, row and byte limits remove oldest polls and unreferenced bodies. SQLite
incremental vacuum and WAL truncation reclaim actual disk pages. The byte cap
is maintained at cleanup boundaries with conservative insertion headroom;
filesystem/page overhead and temporary journal writes are not an OS quota.
The free-space guard refuses further writes before consuming its reserve.
Failure exits the worker and is visible in systemd/journald. It never disables
the live demo's independent 48-hour retention. Atomic transactions and a
single-writer process lock make restart safe. Source hashes survive restarts.

Requests use validated TLS, no credentials, no redirects, 10-second HTTP phase
timeouts, a 20-second deadline checked as chunks arrive and no immediate retries.
HTTP 429/503 `Retry-After` seconds or HTTP-date delays are respected (minimum
60 seconds); absent/invalid values defer one minute. Cooldowns are local to the
running process. A failed feed does not suppress the other feeds. Eight sequential
slow feeds can make a cycle exceed its 60-second target; receipt timestamps
expose the actual cadence. The worker does not silently claim exact sampling.

## Completed UTC days → Parquet

Install the optional pinned `requirements.history-export.txt` to enable
`python -m worker.history_export --state-dir var/history`. This command makes
no network calls. It exports only completed UTC days to
`parquet/YYYY-MM-DD/observations.parquet` with a sibling `manifest.json`.
Today remains in the raw archive until the next daily run.

Each successful poll supplies typed trip/stop estimates, optional standard
direction, vehicle position/time, and alert records. Source and receipt times
remain separate. Missing fields are null; a vehicle timestamp never becomes
an arrival time. Every failed or unparseable poll also has a `poll` row, so
filtering entity rows cannot silently erase feed outages. Trip-level and
stop-level schedule relationships are retained. Standard alert contents are
preserved as JSON; MTA-specific extension interpretation is not implemented,
but original protobuf bodies retain those fields within raw retention.

The exporter streams 4,096-row batches into Zstandard-compressed Parquet.
Publication atomically renames a staged day directory only after verifying raw
snapshot hashes, Parquet row counts and its file hash. The manifest records
counts by record type/status, source poll range, schema version, extractor hash
and PyArrow version. Reruns verify existing immutable files rather than
overwriting them. Partial failures leave no published partial day and never
delete raw rows. A single export lock prevents overlapping timer/manual jobs.

Daily exports default to **90 days or 10 GiB, whichever comes first**, with the
same 2 GiB free-space guard. The bounded raw collector remains **7 days or
2 GiB, whichever comes first**, independently of export success. An export
outage or unexpected input volume can therefore cause raw observations to
expire before export; this is an explicit disk-safety policy, not lossless
archival. The manifest's poll range and counts describe retained coverage,
not a guarantee of a complete day. Measure compression and query coverage
before promising months of uninterrupted history. The two dataset caps total
12 GiB, excluding executables, dependencies and small metadata files.

## Isolated VPS deployment

Stage only `worker/__init__.py`, `worker/history.py`, `requirements.history.txt`
and `infra/mta-history.service` in `/srv/mta-history`, root-owned and read-only
to the service. Create `/srv/mta-history/.venv` and install the minimal history
requirements there. The unit runs as a dynamic unprivileged user, binds no
port, and can write only its `StateDirectory=mta-history`. Review the defaults
against measured free space before enabling:

```sh
sudo cp infra/mta-history.service /etc/systemd/system/mta-history.service
sudo systemctl daemon-reload
sudo systemctl enable --now mta-history
sudo systemctl status mta-history --no-pager
sudo journalctl -u mta-history -n 30 --no-pager
sudo /srv/mta-history/.venv/bin/python -m worker.history \
  --state-dir /var/lib/mta-history --status
```

Run the last Python command from `/srv/mta-history` (or set `PYTHONPATH` there).
No nginx, paid API, DNS, existing database or model migration is needed.
Rollback is `systemctl disable --now mta-history`; keep the state directory for
audit instead of deleting observations. For an archive backup, stop this worker
briefly or use SQLite's online backup API; do not copy a live main DB without
its WAL. With a single VPS this is not an offsite disaster-recovery guarantee.

For daily export, additionally stage `worker/history_export.py` and
`requirements.history-export.txt`; install its requirements in the same venv.
Both service units explicitly use the same dynamic `User=mta-history` and
state directory. The export service has no network and a separate 512 MiB
memory cap. Its timer runs at 00:15 UTC plus up to five minutes of jitter;
missed schedules run on restart:

```sh
sudo /srv/mta-history/.venv/bin/python -m pip install -r requirements.history-export.txt
sudo cp infra/mta-history-export.service infra/mta-history-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mta-history-export.timer
sudo systemctl start mta-history-export.service
sudo systemctl list-timers mta-history-export.timer --no-pager
sudo journalctl -u mta-history-export -n 20 --no-pager
```

On the first collection day, a successful export normally returns `[]` because
there are no completed days yet. To stop exports, disable the timer; stopping
collection does not remove already exported days. Long streaming exports keep
a SQLite read snapshot briefly, which can delay WAL reclamation; memory/time
and disk guards bound this operational trade-off. If a reader pins WAL and the
raw cap is reached, the collector refuses writes instead of deleting more raw
rows trying to reclaim pinned pages. Monitor both service units.

For acceptance, confirm at least two successful collection cycles, advancing
receipt timestamps, and the actual source freshness separately for each feed.
After the first completed UTC day, inspect its manifest, check `polls > 0`,
verify `sha256sum observations.parquet`, and compare the Parquet metadata row
count to `rows`. A successful timer with `[]` is expected on day one, not proof
of a historical export. Capture failures with `journalctl -u mta-history-export`
and `systemctl show mta-history-export -p Result -p ExecMainStatus`; do not label
the latest day complete while a staging/error condition exists. A failing
export retries on the next daily schedule or an explicit operator restart.
No automated email/page alerting is implemented by these units.

## Verification and next boundary

```sh
PYTHONPATH=. python -m pytest tests/test_history_unit.py
# Requires the optional PyArrow dependency:
PYTHONPATH=. python -m pytest tests/test_history_export_unit.py
```

Offline tests cover byte-identical payloads, extension preservation, duplicate
responses, source freshness, lock ownership, restart, transaction rollback,
age/row/disk reclamation, low-space refusal, malformed/oversize payloads,
network failures and per-feed cooldowns. They do not contact MTA or prove
long-duration production uptime.

Export tests cover nulls/freshness, UTC completion boundaries, source/file hash
validation, expected row counts, immutable reruns, corrupt artifacts, rollback
after write failure, disk refusal and independent raw retention.
CI runs these in a separate five-minute job with the optional PyArrow package;
the general API job does not need to install it.

The [offline temporal pipeline](TEMPORAL_EVALUATION.md) now implements
trip/service-date-aware proxy derivation, chronological holdouts, simple baselines
and explicit readiness gates. Static GTFS/extension provenance, separate incident
labels and graph-model evaluation remain separate work. Raw data and temporal
results remain separate from the 216-row constructed evaluation fixture.
