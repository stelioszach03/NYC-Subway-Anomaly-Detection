from __future__ import annotations

import sys
from typing import Optional

from loguru import logger as _logger

from .config import get_settings


_configured: bool = False


def _configure_once() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    _logger.remove()
    _logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        serialize=True,  # JSON lines for easy ingestion
    )
    _configured = True


def get_logger(name: Optional[str] = None):
    """Return a Loguru logger bound with app context and module name."""
    _configure_once()
    s = get_settings()
    return _logger.bind(
        logger=name or __name__,
        service=s.APP_NAME,
        env=s.APP_ENV,
        version=s.APP_VERSION,
    )
