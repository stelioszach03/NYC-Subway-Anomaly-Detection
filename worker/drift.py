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


@dataclass
class DriftMonitor:
    adwin: ADWIN

    def update(self, value: float) -> bool:
        self.adwin.update(value)
        if self.adwin.change_detected:
            log.warning("ADWIN change detected: width={} est={}", self.adwin.width, self.adwin.estimation)
            return True
        return False

    def reset(self) -> None:
        self.adwin = ADWIN()


def save_model(models_dir: str, obj: object, prefix: str = "model") -> Optional[str]:
    try:
        os.makedirs(models_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        path = os.path.join(models_dir, f"{prefix}-{ts}.pkl")
        with open(path, "wb") as f:
            pickle.dump(obj, f)
        log.info("saved model: {}", path)
        return path
    except Exception as e:
        log.warning("failed to save model: {}", repr(e))
        return None


def load_latest_model(models_dir: str) -> Optional[object]:
    try:
        if not os.path.isdir(models_dir):
            return None
        files = [f for f in os.listdir(models_dir) if f.endswith(".pkl")]
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

