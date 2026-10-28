"""Pydantic schemas for scenarios."""

from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel


class CandleData(BaseModel):
    """Single candlestick structure."""
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = 0.0


class ScenarioPublicResponse(BaseModel):
    """Scenario response for user practice session (symbol and date hidden to prevent hindsight)."""
    id: int
    event_type: str
    entry_price: float
    current_price: float
    drop_pct: float
    candles: List[Any]
    trades_today: int
    last_trade_was_loss: bool

    class Config:
        from_attributes = True


class ScenarioRevealResponse(BaseModel):
    """Scenario full reveal after user decision."""
    id: int
    symbol: str
    outcome_2m: Optional[float]
    outcome_5m: Optional[float]
    outcome_10m: Optional[float]
    outcome_30m: Optional[float]

    class Config:
        from_attributes = True
