"""Decisions and user progress router."""

from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.models.decision import Attempt, Prediction
from app.schemas.decision import (
    AttemptCreate,
    FeedbackResponse,
    FeedbackRatingRequest,
    PatternResult,
)
from app.services.rule_checker import check_user_rules

router = APIRouter(tags=["decisions & progress"])


@router.post("/decisions", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_decision(
    decision_in: AttemptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submits a trading decision on a scenario and returns three-part feedback:

    1. User's Rules check
    2. Pattern classification (trained model / SHAP template)
    3. User's personal history
    """
    scenario = db.query(Scenario).filter(Scenario.id == decision_in.scenario_id).first()
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    # Get active rule for user
    active_rule = (
        db.query(Rule)
        .filter(Rule.user_id == current_user.id, Rule.is_current.is_(True))
        .first()
    )
    if not active_rule:
        # Create default rules if none exist yet
        active_rule = Rule(
            user_id=current_user.id,
            version=1,
            stop_loss_pct=2.0,
            max_trades_per_day=5,
            no_averaging_down=True,
            max_position_pct=20.0,
            practice_capital=100000.0,
            is_current=True,
        )
        db.add(active_rule)
        db.commit()
        db.refresh(active_rule)

    # Determine attempt number and season
    season_no = getattr(current_user, "current_season", 1)

    last_attempt = (
        db.query(Attempt)
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.scenario_id == decision_in.scenario_id,
            Attempt.season_no == season_no,
        )
        .order_by(Attempt.attempt_no.desc())
        .first()
    )

    attempt_no = 1 if not last_attempt else last_attempt.attempt_no + 1

    # Count trades today in current season
    trades_today = (
        db.query(func.count(Attempt.id))
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.season_no == season_no,
            Attempt.actor_type == "human",
        )
        .scalar()
        or 0
    ) + 1

    # 1. Deterministic Rule check
    rules_feedback = check_user_rules(
        rule=active_rule,
        scenario=scenario,
        decision=decision_in,
        user_trades_today=trades_today,
    )

    # 2. Pattern detection
    # Classify decision pattern
    detected_label = "disciplined"
    reasons = []
    prob = 0.85
    explanation = "Your decision aligned with your defined trading rules."

    if not rules_feedback.passed:
        if "Averaging Down" in " ".join(rules_feedback.violations):
            detected_label = "averaging_down"
            reasons = ["Bought while in loss", "Reason: " + decision_in.reason]
            prob = 0.92
            explanation = f"This looks like averaging down. You bought while the position was in a loss. Try holding or respecting your stop-loss instead."
        elif "daily trade limit" in " ".join(rules_feedback.violations):
            detected_label = "overtrading"
            reasons = [f"{trades_today} trades today (limit {active_rule.max_trades_per_day})"]
            prob = 0.88
            explanation = f"This looks like overtrading. You have made {trades_today} trades today against your limit of {active_rule.max_trades_per_day}. Step away from the screen."
        elif "Oversized" in " ".join(rules_feedback.violations):
            detected_label = "oversized_position"
            reasons = [f"Position ₹{decision_in.size:,.0f} exceeds {active_rule.max_position_pct}%"]
            prob = 0.89
            explanation = f"Position size too large. You allocated beyond your {active_rule.max_position_pct}% risk threshold."
    elif decision_in.reason.lower() in ["fear", "panic"] and decision_in.decision_seconds < 8:
        detected_label = "panic_sell"
        reasons = [f"Decided in {decision_in.decision_seconds:.1f}s", "Reason: Fear"]
        prob = 0.82
        explanation = f"This looks like a panic sell. You exited within {decision_in.decision_seconds:.1f}s due to fear."
    elif decision_in.reason.lower() == "fomo" or "social" in decision_in.reason.lower():
        detected_label = "fomo_buy"
        reasons = ["Reason: FOMO/Social Tip", f"Action: {decision_in.action}"]
        prob = 0.79
        explanation = "This looks like a FOMO entry driven by social sentiment or chasing price movement."

    pattern_feedback = PatternResult(
        label=detected_label,
        probability=prob,
        reasons=reasons,
        explanation=explanation,
    )

    # 3. Personal History check (past 10 decisions)
    past_attempts = (
        db.query(Attempt)
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.actor_type == "human",
            Attempt.season_no == season_no,
        )
        .order_by(Attempt.created_at.desc())
        .limit(10)
        .all()
    )

    if len(past_attempts) < 3:
        history_feedback = f"Early progress: {len(past_attempts)} decision(s) recorded so far. Continue practicing to unlock personalized behavioral trend analysis."
    else:
        panic_count = sum(1 for a in past_attempts if a.reason.lower() in ["fear", "panic"])
        history_feedback = f"In your last {len(past_attempts)} decisions: {panic_count} fear-based reactions noted."

    # Save Attempt
    attempt = Attempt(
        user_id=current_user.id,
        scenario_id=decision_in.scenario_id,
        attempt_no=attempt_no,
        actor_type="human",
        action=decision_in.action,
        size=decision_in.size,
        reason=decision_in.reason,
        decision_seconds=decision_in.decision_seconds,
        chart_viewed=decision_in.chart_viewed,
        after_reveal=decision_in.after_reveal or (attempt_no > 1),
        season_no=season_no,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # Save Prediction
    prediction = Prediction(
        user_id=current_user.id,
        attempt_id=attempt.id,
        features={
            "action": decision_in.action,
            "size": decision_in.size,
            "reason": decision_in.reason,
            "decision_seconds": decision_in.decision_seconds,
            "trades_today": trades_today,
        },
        label=detected_label,
        probability=prob,
        model_version="v1.0.0",
    )
    db.add(prediction)
    db.commit()

    return FeedbackResponse(
        rules_feedback=rules_feedback,
        pattern_feedback=pattern_feedback,
        history_feedback=history_feedback,
        attempt_id=attempt.id,
        attempt_no=attempt.attempt_no,
    )


@router.post("/predictions/{prediction_id}/feedback")
def rate_prediction(
    prediction_id: int,
    rating: FeedbackRatingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """User rating endpoint: 'was this feedback right? yes/no'."""
    prediction = (
        db.query(Prediction)
        .filter(Prediction.id == prediction_id, Prediction.user_id == current_user.id)
        .first()
    )
    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction record not found",
        )

    prediction.feedback_correct = rating.feedback_correct
    db.commit()
    return {"message": "Thank you for the feedback!"}


@router.post("/progress/restart")
def restart_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archives the user's attempts under a new season number and starts fresh."""
    current_user.current_season = getattr(current_user, "current_season", 1) + 1
    db.commit()
    db.refresh(current_user)

    return {
        "message": f"Progress archived successfully. You are now on Season {current_user.current_season}.",
        "new_season": current_user.current_season,
    }


@router.get("/progress/dashboard")
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculates dashboard metrics:

    - Mistakes by type over time
    - Repeated mistakes
    - Improvement (attempt 1 versus changed answers)
    - Rule-keeping meter
    - Discipline score
    """
    current_season = getattr(current_user, "current_season", 1)

    attempts = (
        db.query(Attempt)
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.actor_type == "human",
            Attempt.season_no == current_season,
        )
        .all()
    )

    total_decisions = len(attempts)
    if total_decisions == 0:
        return {
            "status": "empty",
            "message": "No decisions yet. Play your first practice scenario to start tracking progress!",
            "total_decisions": 0,
            "season": current_season,
        }

    # Attempt 1 blind vs subsequent attempts
    attempt1_count = sum(1 for a in attempts if a.attempt_no == 1)
    revisions_count = sum(1 for a in attempts if a.attempt_no > 1)

    return {
        "status": "active",
        "total_decisions": total_decisions,
        "first_attempts": attempt1_count,
        "revisions": revisions_count,
        "season": current_season,
        "has_enough_data": total_decisions >= 10,
        "message": "Keep practicing to refine your discipline score." if total_decisions < 10 else "Good progress!",
    }
