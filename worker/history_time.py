"""Explicit availability semantics for old request-start and new receipt polls."""

import json
import math


def poll_availability(poll):
    if "available_ts" in poll:
        value = poll["available_ts"]
        return (value if type(value) is int else None, poll.get("availability_semantics", "unknown"))
    try:
        metadata = json.loads(poll.get("metadata_json") or "{}")
    except (ValueError, TypeError):
        return None, "unknown"
    observed = poll.get("observed_ts")
    if type(observed) is not int:
        return None, "unknown"
    if metadata.get("timestamp_semantics") == "response_available_v2":
        # Receipt is stored in whole seconds; the extra second is conservative.
        return observed + 1, "response_available_v2_plus_second_guard"
    latency = poll.get("latency_ms", poll.get("poll_latency_ms"))
    if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
        return None, "unknown"
    # Legacy observed_ts was request start, not receipt. Preserve the old bytes
    # and expose this reconstruction as estimated, not an exact receipt clock.
    return observed + math.ceil(latency / 1000) + 2, "legacy_start_plus_latency_and_two_second_guard"
