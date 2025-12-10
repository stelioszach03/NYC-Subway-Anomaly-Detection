from __future__ import annotations

import pandas as pd

from worker.features import build_feature_frame, feature_vector_from_row


def test_build_feature_frame_adds_temporal_and_context_columns():
    df = pd.DataFrame(
        [
            {
                'id': 1,
                'route_id': 'A',
                'stop_id': 'A15N',
                'observed_ts': '2026-02-05T12:00:00Z',
                'event_ts': '2026-02-05T12:03:00Z',
                'headway_sec': 240,
                'precipitation_mm': 0.0,
                'weather_severity': 0.0,
                'service_alert_active': 0.0,
                'service_alert_severity': 0.0,
            },
            {
                'id': 2,
                'route_id': 'A',
                'stop_id': 'A15N',
                'observed_ts': '2026-02-05T12:05:00Z',
                'event_ts': '2026-02-05T12:08:00Z',
                'headway_sec': 255,
                'precipitation_mm': 0.0,
                'weather_severity': 0.0,
                'service_alert_active': 0.0,
                'service_alert_severity': 0.0,
            },
            {
                'id': 3,
                'route_id': 'A',
                'stop_id': 'A15N',
                'observed_ts': '2026-02-05T12:10:00Z',
                'event_ts': '2026-02-05T12:09:10Z',
                'headway_sec': 420,
                'precipitation_mm': 4.0,
                'weather_severity': 1.0,
                'service_alert_active': 1.0,
                'service_alert_severity': 0.8,
            },
        ]
    )

    frame = build_feature_frame(df)

    assert list(frame['id']) == [1, 2, 3]
    assert {'hour', 'day_of_week', 'is_peak', 'lag_headway_1', 'rolling_mean_6', 'station_baseline_deviation', 'feed_delay_sec'} <= set(frame.columns)

    latest = frame.iloc[-1].to_dict()
    assert latest['direction_code'] == 1.0
    assert latest['lag_headway_1'] == 255.0
    assert latest['rolling_mean_6'] >= 240.0
    assert latest['precipitation_mm'] == 4.0
    assert latest['service_alert_active'] == 1.0
    assert latest['feed_delay_sec'] > 0.0

    vector = feature_vector_from_row(latest)
    assert vector['lag_headway_1'] == 255.0
    assert vector['service_alert_active'] == 1.0
    assert vector['weather_severity'] == 1.0
