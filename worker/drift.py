"""Drift detection utilities using ADWIN over absolute residuals."""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from river.drift import ADWIN

from .util import get_logger


log = get_logger(__name__)


# Keep only the N most recent model checkpoints on disk per prefix.
# Configurable via env var so ops can tune without redeploy.
DEFAULT_MODEL_RETENTION = int(os.environ.get("MODEL_RETENTION", "5"))


@dataclass
class DriftMonitor:
    adwin: ADWIN

    def update(self, value: float) -> bool:
        self.adwin.update(value)
        changed = bool(
            getattr(self.adwin, "drift_detected", False) or getattr(self.adwin, "change_detected", False)
        )
        if changed:
            log.warning("ADWIN change detected: width={} est={}", self.adwin.width, self.adwin.estimation)
            return True
        return False

    def reset(self) -> None:
        self.adwin = ADWIN()


def _cleanup_old_checkpoints(
    models_dir: str,
    prefix: str,
    retention: int,
) -> int:
    """Remove stale checkpoints, keeping only the `retention` most recent.

    Safe to call repeatedly: file names are timestamped so a lexicographic
    reverse sort orders newest-first.

    Returns the number of files removed.
    """
    if retention <= 0:
        return 0
    try:
        files = [
            f for f in os.listdir(models_dir)
            if f.startswith(f"{prefix}-") and f.endswith(".pkl")
        ]
    except FileNotFoundError:
        return 0
    except Exception as e:
        log.warning("retention listdir failed: {}", repr(e))
        return 0

    if len(files) <= retention:
        return 0

    files.sort(reverse=True)
    stale = files[retention:]
    removed = 0
    for name in stale:
        target = os.path.join(models_dir, name)
        try:
            os.remove(target)
            removed += 1
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("retention unlink failed for {}: {}", name, repr(e))
    if removed:
        log.info("retention cleanup: removed {} stale checkpoints ({})", removed, prefix)
    return removed


def save_model(
    models_dir: str,
    obj: object,
    prefix: str = "model",
    retention: Optional[int] = None,
) -> Optional[str]:
    """Atomically persist a model checkpoint and prune older ones.

    The pickle is written to a temporary `.pkl.tmp` then renamed into place
    to avoid partial reads by the loader. After the rename we keep only the
    `retention` (default: 5) most recent checkpoints on disk.
    """
    try:
        os.makedirs(models_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        final_path = os.path.join(models_dir, f"{prefix}-{ts}.pkl")
        tmp_path = final_path + ".tmp"

        with open(tmp_path, "wb") as f:
            pickle.dump(obj, f)
        os.replace(tmp_path, final_path)

        log.info("saved model: {}", final_path)

        keep = DEFAULT_MODEL_RETENTION if retention is None else int(retention)
        _cleanup_old_checkpoints(models_dir, prefix, keep)

        return final_path
    except Exception as e:
        log.warning("failed to save model: {}", repr(e))
        return None


def load_latest_model(models_dir: str) -> Optional[object]:
    try:
        if not os.path.isdir(models_dir):
            return None
        files = [
            f for f in os.listdir(models_dir)
            if f.endswith(".pkl") and not f.endswith(".pkl.tmp")
        ]
        if not files:
            return None
        files.sort(reverse=True)
        path = os.path.join(models_dir, files[0])
        with open(path, "rb") as f:
            obj = pickle.load(f)
        log.info("loaded model: {}", path)
        return obj
    except Exception as e:
        log.warning("failed to load model: {}", repr(e))
        return None
