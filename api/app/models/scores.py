from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, Float, Index, BigInteger, String, Integer
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    # Observed timestamp: when this row was observed/ingested (UTC)
    observed_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Event timestamp: optional predicted/scheduled arrival/departure time from GTFS-RT
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    route_id: Mapped[str] = mapped_column(String, nullable=False)
    stop_id: Mapped[str] = mapped_column(String, nullable=False)
    # Raw observed/derived headway in seconds from collector stage
    headway_sec: Mapped[float] = mapped_column(Float, nullable=True)
    # Model prediction for headway in seconds
    predicted_headway_sec: Mapped[float] = mapped_column(Float, nullable=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    residual: Mapped[float] = mapped_column(Float, nullable=True)
    window_sec: Mapped[int] = mapped_column(Integer, nullable=True)

Index("ix_scores_observed_ts_route_stop", Score.observed_ts, Score.route_id, Score.stop_id)
Index("ix_scores_observed_ts", Score.observed_ts)
