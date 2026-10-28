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
    
    # Context
    trades_today = Column(Integer, default=1, nullable=False)
    last_trade_was_loss = Column(Boolean, default=False, nullable=False)
    
    # Lifecycle
    active = Column(Boolean, default=True, nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    created_on = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    attempts = relationship("Attempt", back_populates="scenario", cascade="all, delete-orphan")
    bot_decisions = relationship("BotDecision", back_populates="scenario", cascade="all, delete-orphan")
