"""Pydantic schemas for trading rules."""

from datetime import datetime
from pydantic import BaseModel, Field


class RuleBase(BaseModel):
    """Trading rules baseline attributes."""
    stop_loss_pct: float = Field(..., gt=0, le=100, description="Stop loss percentage")
    max_trades_per_day: int = Field(..., gt=0, le=100, description="Maximum trades allowed per day")
    no_averaging_down: bool = Field(default=True, description="Enforce no averaging down rule")
    max_position_pct: float = Field(..., gt=0, le=100, description="Maximum single position % of capital")
    practice_capital: float = Field(..., gt=0, description="Practice capital amount chosen by user")


class RuleCreate(RuleBase):
    """Request schema to create or update rules."""
    pass


class RuleResponse(RuleBase):
    """Response schema for active or historic rule."""
    id: int
    user_id: int
    version: int
    is_current: bool
    created_at: datetime

    class Config:
        from_attributes = True
