"""Read-only collection coverage report; this is not incident-model evaluation."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import time

from worker.history import FEEDS


def profile_rows(rows, now, gap_threshold_seconds=120):
    if gap_threshold_seconds < 1:
        raise ValueError('Gap threshold must be positive')
    grouped = defaultdict(list)
    for row in rows:
        if row['feed'] not in FEEDS:
            raise ValueError('Unexpected feed identity')
        if row['observed_ts'] > now:
            raise ValueError('Receipt lies after the analysis cutoff')
        grouped[row['feed']].append(row)
    feed_reports = []
    for feed in FEEDS:
        values = sorted(grouped[feed], key=lambda row: (row['observed_ts'], row['id']))
        times = [r['observed_ts'] for r in values]
        intervals = [b - a for a, b in zip(times, times[1:])]
        gaps = [v for v in intervals if v > gap_threshold_seconds]
        source_ages = [r['observed_ts'] - r['source_ts'] for r in values if r['source_ts'] is not None]
        fresh_success = sum(r['status'] == 'ok' and r['freshness'] == 'fresh' for r in values)
        feed_reports.append({
            'feed': feed, 'polls': len(values), 'status_counts': dict(Counter(r['status'] for r in values)),
            'receipt_freshness_counts': dict(Counter(r['freshness'] for r in values)),
            'fresh_success_fraction_of_all_polls': fresh_success / len(values) if values else None,
            'first_receipt_ts': times[0] if times else None, 'last_receipt_ts': times[-1] if times else None,
            'last_receipt_age_s': now - times[-1] if times else None,
            'recorded_interval_span_s': times[-1] - times[0] if times else None,
            'inter_poll_interval_median_s': statistics.median(intervals) if intervals else None,
            'inter_poll_interval_max_s': max(intervals) if intervals else None,
            'gaps_over_threshold': len(gaps), 'gap_duration_sum_s': sum(gaps),
            'current_trailing_gap_over_threshold': now - times[-1] > gap_threshold_seconds if times else None,
            'source_age_at_receipt_median_s': statistics.median(source_ages) if source_ages else None,
            'source_age_missing_polls': sum(r['source_ts'] is None for r in values),
        })
    return {'schema': 'mta-history-quality-v1', 'analysis_cutoff_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'polls': sum(x['polls'] for x in feed_reports), 'expected_feeds': len(FEEDS),
            'feeds_with_records': sum(r['polls'] > 0 for r in feed_reports), 'gap_threshold_seconds': gap_threshold_seconds,
            'feeds': feed_reports,
            'limitations': [
                'Retained receipt coverage only; not an uninterrupted-uptime or exact sampling guarantee.',
                'Failed polls stay in freshness denominators. Missing source timestamps remain missing.',
                'No invented observations before the first retained receipt or after the analysis cutoff.',
                'Gap durations measure elapsed time between receipts, not proved missing requests.',
                'Transit incident labels, forecasting accuracy and station/route coverage are not measured here.',
            ]}


def profile_database(database, now=None):
    now = int(time.time()) if now is None else int(now)
    uri = Path(database).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        rows = [dict(r) for r in db.execute('SELECT id,observed_ts,feed,status,source_ts,freshness FROM polls WHERE observed_ts<=? ORDER BY id', (now,))]
    result = profile_rows(rows, now)
    result['canonical_input_rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    result['analysis_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = profile_database(args.database)
    # Explicit new artifact; never silently overwrite an earlier cutoff report.
    with args.output.open('x') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'polls': result['polls'], 'feeds_with_records': result['feeds_with_records'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
