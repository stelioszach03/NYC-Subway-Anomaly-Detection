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


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = _coerce_psycopg_dialect(settings.DB_URL)
        _engine = create_engine(url, pool_pre_ping=True, future=True)
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
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
