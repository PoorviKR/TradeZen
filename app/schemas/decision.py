"""Pydantic schemas for decisions, reasons, attempts, and feedback."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ReasonItem(BaseModel):
    """Single action-scoped decision reason."""

    code: str
    action: str
    label: str
    kind: str
    display_order: int = 0
    catalogue_version: str

    class Config:
        from_attributes = True


class ReasonsResponse(BaseModel):
    """Response payload for action-filtered reasons."""

    catalogue_version: str
    action: str
    reasons: List[ReasonItem]


class AttemptCreate(BaseModel):
    """User decision submission on a scenario."""

    scenario_id: int
    action: str = Field(..., pattern="^(buy|sell|hold)$")
    size: float = Field(..., gt=0)
    reason_code: Optional[str] = Field(default=None, max_length=50)
    reason: Optional[str] = Field(default=None, min_length=2, max_length=200)
    note: Optional[str] = Field(default=None, max_length=300)
    decision_seconds: float = Field(..., ge=0)
    chart_viewed: bool = True
    after_reveal: bool = False


class RuleCheckResult(BaseModel):
    """Deterministic rule validation and consistency check feedback."""

    passed: bool
    violations: List[str]
    rule_summary: str
    rule_version: Optional[int] = None
    consistency_warnings: List[str] = Field(default_factory=list)
    consistency_flags: Dict[str, bool] = Field(default_factory=dict)


class PatternResult(BaseModel):
    """Machine learning pattern classification and explanation."""

    label: str
    probability: float
    reasons: List[str]
    explanation: str
    available: bool = True


class FeedbackResponse(BaseModel):
    """Three-part feedback card response."""

    rules_feedback: RuleCheckResult
    pattern_feedback: PatternResult
    history_feedback: str
    attempt_id: int
    attempt_no: int
    reason_code: Optional[str] = None
    reason_kind: Optional[str] = None
    catalogue_version: Optional[str] = None


class FeedbackRatingRequest(BaseModel):
    """User rating: was this feedback right? (yes/no)"""

    feedback_correct: bool
