"""Scenario snapshot model definition."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class Scenario(Base):
    """Immutable market scenario snapshot with past context and future outcomes."""

    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False)  # Stored internally, hidden from frontend during play
    event_type = Column(String(20), nullable=False, index=True)  # 'drop', 'spike', 'calm'
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    drop_pct = Column(Float, nullable=False)
    
    # JSON array of candles shown to user: [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]
    candles = Column(JSON, nullable=False)
    
    # Outcomes revealed after decision
    outcome_2m = Column(Float, nullable=True)
    outcome_5m = Column(Float, nullable=True)
    outcome_10m = Column(Float, nullable=True)
    outcome_30m = Column(Float, nullable=True)
    outcome_candles = Column(JSON, nullable=True)  # Future candles for 2, 5, 10, 30 min reveal charts
    
    # Context & Calibration
    trades_today = Column(Integer, default=1, nullable=False)
    last_trade_was_loss = Column(Boolean, default=False, nullable=False)
    thresholds = Column(JSON, nullable=True)  # Detection threshold details used for this scenario
    
    # Lifecycle
    active = Column(Boolean, default=True, nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=True, index=True)
    created_on = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    attempts = relationship("Attempt", back_populates="scenario", cascade="all, delete-orphan")
    bot_decisions = relationship("BotDecision", back_populates="scenario", cascade="all, delete-orphan")


class RawCandle(Base):
    """Raw 1-minute historical candlestick data for the rolling 20-trading-day window."""

    __tablename__ = "raw_candles"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    trading_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    timestamp = Column(Integer, nullable=False, index=True)  # Epoch seconds
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PoolReport(Base):
    """Summary report for each scenario pool generation run."""

    __tablename__ = "pool_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    window_start = Column(String(10), nullable=False)
    window_end = Column(String(10), nullable=False)
    total_scenarios = Column(Integer, default=0, nullable=False)
    drop_count = Column(Integer, default=0, nullable=False)
    spike_count = Column(Integer, default=0, nullable=False)
    calm_count = Column(Integer, default=0, nullable=False)
    thresholds_used = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

