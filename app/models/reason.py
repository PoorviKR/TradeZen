"""SQLAlchemy model for the versioned ScenarioSimulation reason catalogue (`scn_reasons`)."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime

from app.db.base import Base


class ScnReason(Base):
    """Canonical database catalogue of action-dependent trading reasons."""

    __tablename__ = "scn_reasons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    action = Column(String(20), nullable=False, index=True)  # 'buy', 'hold', 'sell'
    label = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False, index=True)  # 'plan', 'mixed', 'emotion', 'external', 'unsure'
    catalogue_version = Column(String(20), nullable=False, index=True)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
