"""Decision attempts, bot simulations, and ML prediction models."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class Attempt(Base):
    """User attempt on a scenario."""

    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_no = Column(Integer, default=1, nullable=False)  # 1 is blind first try, 2+ are revisions
    actor_type = Column(String(20), default="human", nullable=False, index=True)
    
    action = Column(String(20), nullable=False)  # 'buy', 'sell', 'hold'
    size = Column(Float, nullable=False)
    reason = Column(String(200), nullable=False)  # Legacy or label text
    reason_code = Column(String(50), nullable=True, index=True)
    reason_kind = Column(String(20), nullable=True, index=True)
    catalogue_version = Column(String(20), nullable=True, index=True)
    migrated = Column(Boolean, default=False, server_default="false", nullable=False)
    note = Column(String(300), nullable=True)
    rule_version = Column(Integer, nullable=True)
    decision_seconds = Column(Float, nullable=False)
    chart_viewed = Column(Boolean, default=True, nullable=False)
    after_reveal = Column(Boolean, default=False, nullable=False)
    season_no = Column(Integer, default=1, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="attempts")
    scenario = relationship("Scenario", back_populates="attempts")
    prediction = relationship("Prediction", back_populates="attempt", uselist=False)


class BotDecision(Base):
    """Simulated bot decisions used to build ML training data."""

    __tablename__ = "bot_decisions"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_type = Column(String(20), default="bot", nullable=False, index=True)
    bot_name = Column(String(50), nullable=False)  # Panic, Averaging, FOMO, Revenge, Disciplined
    true_label = Column(String(50), nullable=False)  # Actual behavior shown
    action = Column(String(20), nullable=False)
    size = Column(Float, nullable=False)
    reason = Column(String(120), nullable=False)
    reason_code = Column(String(50), nullable=True, index=True)
    reason_kind = Column(String(20), nullable=True, index=True)
    catalogue_version = Column(String(20), nullable=True, index=True)
    migrated = Column(Boolean, default=False, server_default="false", nullable=False)
    decision_seconds = Column(Float, nullable=False)
    features = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    scenario = relationship("Scenario", back_populates="bot_decisions")


class Prediction(Base):
    """Model predictions and user feedback on explanations."""

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True, index=True)
    features = Column(JSON, nullable=False)
    label = Column(String(50), nullable=False)
    probability = Column(Float, nullable=False)
    model_version = Column(String(50), nullable=False)
    feedback_correct = Column(Boolean, nullable=True)  # User rating: was this feedback right? (True/False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="predictions")
    attempt = relationship("Attempt", back_populates="prediction")
