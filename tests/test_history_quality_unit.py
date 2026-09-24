from worker.history_quality import profile_rows


def row(i, time, status='ok', freshness='fresh', source=0):
    return dict(id=i, observed_ts=time, feed='ACE', status=status, freshness=freshness, source_ts=source)


def ace(result):
    return next(x for x in result['feeds'] if x['feed'] == 'ACE')


def test_failures_and_unknown_times_remain_in_denominator():
    result = ace(profile_rows([row(1, 100, source=90), row(2, 160, 'network_error', 'unknown', None)], 170))
    assert result['polls'] == 2
    assert result['fresh_success_fraction_of_all_polls'] == 0.5
    assert result['source_age_missing_polls'] == 1
    assert result['source_age_at_receipt_median_s'] == 10


def test_gaps_do_not_fabricate_missing_request_count():
    result = ace(profile_rows([row(1, 100), row(2, 160), row(3, 400)], 550))
    assert result['gaps_over_threshold'] == 1
    assert result['gap_duration_sum_s'] == 240
    assert result['current_trailing_gap_over_threshold'] is True
    assert 'missing_requests' not in result


def test_absent_feeds_report_null_not_perfect_coverage():
    report = profile_rows([], 500)
    assert report['feeds_with_records'] == 0
    assert len(report['feeds']) == 8
    assert all(x['fresh_success_fraction_of_all_polls'] is None for x in report['feeds'])


def test_stale_http_success_is_not_fresh_success():
    result = ace(profile_rows([row(1, 100, freshness='stale')], 105))
    assert result['fresh_success_fraction_of_all_polls'] == 0
