from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.core.config import get_settings


def _coerce_psycopg_dialect(url: str) -> str:
    # Ensure SQLAlchemy uses psycopg (v3) driver when only base postgresql scheme given
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


_engine = None
_SessionLocal = None
_engine_url = None


def get_engine():
    global _engine, _engine_url
    settings = get_settings()
    url = _coerce_psycopg_dialect(settings.DB_URL)
    if _engine is None or _engine_url != url:
        _engine = create_engine(url, pool_pre_ping=True, future=True)
        _engine_url = url
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine(), future=True
        )
    else:
        # Rebind factory if engine changed due env update (common in tests).
        if _SessionLocal.kw.get("bind") is not get_engine():
            _SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=get_engine(), future=True
            )
    return _SessionLocal


def get_db() -> Generator:
    SessionLocal = _get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
