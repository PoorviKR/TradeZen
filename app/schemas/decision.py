"""Pydantic schemas for decisions, attempts, and feedback."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AttemptCreate(BaseModel):
    """User decision submission on a scenario."""
    scenario_id: int
    action: str = Field(..., pattern="^(buy|sell|hold)$")
    size: float = Field(..., gt=0)
    reason: str = Field(..., min_length=2, max_length=100)
    decision_seconds: float = Field(..., ge=0)
    chart_viewed: bool = True
    after_reveal: bool = False


class RuleCheckResult(BaseModel):
    """Deterministic rule validation feedback."""
    passed: bool
    violations: List[str]
    rule_summary: str


class PatternResult(BaseModel):
    """Machine learning pattern classification and explanation."""
    label: str
    probability: float
    reasons: List[str]
    explanation: str


class FeedbackResponse(BaseModel):
    """Three-part feedback card response."""
    rules_feedback: RuleCheckResult
    pattern_feedback: PatternResult
    history_feedback: str
    attempt_id: int
    attempt_no: int


class FeedbackRatingRequest(BaseModel):
    """User rating: was this feedback right? (yes/no)"""
    feedback_correct: bool
