"""User model definition."""

import re
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    """User account model for TradeZen."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    current_season = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    rules = relationship("Rule", back_populates="user", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="user", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="user", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        """Ensure username is always populated to prevent null constraint violations."""
        if "username" not in kwargs or not kwargs.get("username"):
            base = kwargs.get("display_name") or (kwargs.get("email", "").split("@")[0] if kwargs.get("email") else "user")
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(base).lower().strip()).strip("_")
            kwargs["username"] = sanitized[:50] if sanitized else f"user_{int(datetime.now(timezone.utc).timestamp())}"
        super().__init__(**kwargs)
