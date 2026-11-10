import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
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
from app.services.features import compute_history_features, extract_feature_vector
from app.ml.predictor import MLPredictor
from app.ml.explainer import explain_text

logger = logging.getLogger("tradezen.decisions")
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

    # 2. History features (shared function for user, bots, and training)
    past_attempts = (
        db.query(Attempt)
        .options(joinedload(Attempt.prediction))
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.actor_type == "human",
            Attempt.season_no == season_no,
        )
        .order_by(Attempt.created_at.desc())
        .limit(10)
        .all()
    )

    prior_decisions = [
        {
            "label": a.prediction.label if a.prediction else "disciplined",
            "decision_seconds": a.decision_seconds,
            "size": a.size,
            "action": a.action,
            "reason": a.reason,
        }
        for a in reversed(past_attempts)
    ]
    history_features = compute_history_features(prior_decisions)

    # 3. Decision-time feature vector known at decision time
    feature_vec = extract_feature_vector(
        action=decision_in.action,
        size=decision_in.size,
        reason=decision_in.reason,
        decision_seconds=decision_in.decision_seconds,
        chart_viewed=decision_in.chart_viewed,
        scenario_drop_pct=scenario.drop_pct,
        scenario_current_price=scenario.current_price,
        scenario_trades_today=trades_today,
        scenario_last_trade_was_loss=scenario.last_trade_was_loss,
        scenario_event_type=scenario.event_type,
        stop_loss_pct=active_rule.stop_loss_pct,
        max_trades_per_day=active_rule.max_trades_per_day,
        max_position_pct=active_rule.max_position_pct,
        no_averaging_down=active_rule.no_averaging_down,
        practice_capital=active_rule.practice_capital,
        history_features=history_features,
    )

    # 4. ML Pattern detection & SHAP explanation
    try:
        predictor = MLPredictor.get_instance()
        ml_result = predictor.predict(feature_vec)
        detected_label = ml_result["label"]
        prob = ml_result["probability"]
        reasons_list = [r["feature"].replace("_", " ") for r in ml_result["reasons"]]
        explanation = explain_text(feature_vec, ml_result["reasons"], predicted_label=detected_label)
        model_version = ml_result["model_version"]
    except Exception as exc:
        logger.warning("ML inference fallback used: %s", exc)
        detected_label = "disciplined" if rules_feedback.passed else "averaging_down"
        prob = 0.85
        reasons_list = ["Rule alignment" if rules_feedback.passed else "Rule departure"]
        explanation = "Decision evaluated against your defined trading rules."
        model_version = "v1.0.0"

    pattern_feedback = PatternResult(
        label=detected_label,
        probability=prob,
        reasons=reasons_list,
        explanation=explanation,
    )

    # 5. Personal History feedback (past 10 decisions)
    if len(past_attempts) < 3:
        history_feedback = f"Early progress: {len(past_attempts)} decision(s) recorded so far. Continue practicing to unlock personalized behavioral trend analysis."
    else:
        mistake_cnt = int(history_features["history_mistake_count"])
        history_feedback = f"In your last {len(past_attempts)} decisions: {mistake_cnt} pattern deviation(s) noted."

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

    # Save Prediction with decision-time features
    prediction = Prediction(
        user_id=current_user.id,
        attempt_id=attempt.id,
        features=feature_vec,
        label=detected_label,
        probability=prob,
        model_version=model_version,
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
    """Calculates comprehensive dashboard metrics:

    - Mistakes by type over time
    - Repeated mistakes list
    - Improvement (attempt 1 versus changed answers)
    - Rule-keeping meter (%)
    - Discipline score trend
    - Backing decision count claim and 'not enough data yet' under 10 decisions
    """
    current_season = getattr(current_user, "current_season", 1)

    attempts = (
        db.query(Attempt)
        .options(joinedload(Attempt.prediction))
        .filter(
            Attempt.user_id == current_user.id,
            Attempt.actor_type == "human",
            Attempt.season_no == current_season,
        )
        .order_by(Attempt.created_at.asc())
        .all()
    )

    total_decisions = len(attempts)
    if total_decisions == 0:
        return {
            "status": "empty",
            "message": "No decisions yet. Play your first practice scenario to start tracking progress!",
            "total_decisions": 0,
            "season": current_season,
            "has_enough_data": False,
            "data_notice": "not enough data yet",
        }

    # Attempt 1 blind vs revisions
    attempt1_list = [a for a in attempts if a.attempt_no == 1]
    revisions_list = [a for a in attempts if a.attempt_no > 1]

    # Map scenario_id to attempts
    scenario_attempts: Dict[int, List[Attempt]] = {}
    for a in attempts:
        scenario_attempts.setdefault(a.scenario_id, []).append(a)

    # Mistakes breakdown
    mistake_counts = {
        "panic_sell": 0,
        "averaging_down": 0,
        "fomo_buy": 0,
        "revenge_trade": 0,
    }
    friendly_names = {
        "panic_sell": "Panic Sell",
        "averaging_down": "Averaging Down",
        "fomo_buy": "FOMO Buy",
        "revenge_trade": "Revenge Trade",
        "disciplined": "Disciplined",
    }

    disciplined_count = 0
    timeline: List[Dict[str, Any]] = []
    rolling_scores: List[Dict[str, Any]] = []

    recent_window: List[int] = []

    for idx, att in enumerate(attempts, start=1):
        lbl = att.prediction.label if att.prediction else "disciplined"
        is_disc = 1 if lbl == "disciplined" else 0
        if is_disc:
            disciplined_count += 1
        elif lbl in mistake_counts:
            mistake_counts[lbl] += 1

        recent_window.append(is_disc)
        if len(recent_window) > 5:
            recent_window.pop(0)

        rolling_score = round((sum(recent_window) / len(recent_window)) * 100, 1)

        timeline.append({
            "trade_number": idx,
            "label": lbl,
            "friendly_label": friendly_names.get(lbl, lbl),
            "is_mistake": 0 if is_disc else 1,
            "attempt_no": att.attempt_no,
        })

        rolling_scores.append({
            "trade_number": idx,
            "score": rolling_score,
            "date": att.created_at.strftime("%H:%M") if att.created_at else f"#{idx}",
        })

    # Repeated mistakes list (mistakes that occurred >= 2 times)
    repeated_mistakes = [
        {
            "type": m_type,
            "label": friendly_names.get(m_type, m_type),
            "count": count,
            "supporting_decisions": count,
        }
        for m_type, count in mistake_counts.items()
        if count >= 2
    ]
    repeated_mistakes.sort(key=lambda x: x["count"], reverse=True)

    # Improvement calculation (attempt 1 mistake -> revised attempt disciplined)
    improved_scenarios = 0
    scenarios_revised = 0
    for sc_id, sc_atts in scenario_attempts.items():
        if len(sc_atts) > 1:
            scenarios_revised += 1
            first_att = sc_atts[0]
            last_att = sc_atts[-1]
            first_lbl = first_att.prediction.label if first_att.prediction else "disciplined"
            last_lbl = last_att.prediction.label if last_att.prediction else "disciplined"
            if first_lbl != "disciplined" and last_lbl == "disciplined":
                improved_scenarios += 1

    improvement_pct = round((improved_scenarios / max(1, scenarios_revised)) * 100, 1) if scenarios_revised > 0 else 0.0
    rule_compliance_pct = round((disciplined_count / max(1, total_decisions)) * 100, 1)
    discipline_score = rule_compliance_pct

    has_enough_data = total_decisions >= 10

    return {
        "status": "active",
        "season": current_season,
        "total_decisions": total_decisions,
        "first_attempts": len(attempt1_list),
        "revisions": len(revisions_list),
        "has_enough_data": has_enough_data,
        "data_notice": "sufficient data" if has_enough_data else "not enough data yet",
        "decisions_backing_claim": total_decisions,
        "rule_compliance_pct": rule_compliance_pct,
        "discipline_score": discipline_score,
        "mistakes_by_type": mistake_counts,
        "repeated_mistakes": repeated_mistakes,
        "improvement": {
            "scenarios_revised": scenarios_revised,
            "improved_count": improved_scenarios,
            "improvement_pct": improvement_pct,
            "supporting_decisions": scenarios_revised,
        },
        "discipline_trend": rolling_scores,
        "timeline": timeline,
    }
