"""User trading rules model with version tracking."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import Base


class Rule(Base):
    """Trading rules set by a user, with version history."""

    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    stop_loss_pct = Column(Float, nullable=False, default=2.0)
    max_trades_per_day = Column(Integer, nullable=False, default=5)
    no_averaging_down = Column(Boolean, nullable=False, default=True)
    max_position_pct = Column(Float, nullable=False, default=20.0)
    practice_capital = Column(Float, nullable=False, default=100000.0)
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="rules")
