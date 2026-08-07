"""Categorical feature hashes must be stable across processes.

The categorical hash features (route_hash, stop_hash, route_direction_hash) feed
the online River model and are persisted implicitly in its checkpoints. If they
change between process restarts, a reloaded model is scoring a different feature
space than the one it was trained on, and the replay evaluation stops being
reproducible. This previously happened because ``_safe_hash`` used the builtin
``hash``, which CPython randomizes per process via PYTHONHASHSEED.
"""

from __future__ import annotations

import subprocess
import sys

from worker.features import _safe_hash


EXPECTED = {
    ("A", 997): 0.15747241725175526,
    ("A15N", 4093): 0.6457366235035427,
    ("A:N", 1237): 0.4486661277283751,
}


def test_safe_hash_matches_pinned_values():
    for (value, mod), expected in EXPECTED.items():
        assert _safe_hash(value, mod) == expected


def test_safe_hash_empty_value_is_zero():
    assert _safe_hash("", 997) == 0.0


def test_safe_hash_is_stable_under_hash_randomization():
    """Run in fresh interpreters with different PYTHONHASHSEED values."""

    snippet = (
        "from worker.features import _safe_hash;"
        "print(_safe_hash('A15N', 4093))"
    )
    outputs = set()
    for seed in ("0", "1", "12345"):
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "PYTHONPATH": "."},
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, f"hash varied across PYTHONHASHSEED values: {outputs}"
