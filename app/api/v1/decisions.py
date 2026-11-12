"""Decisions, feedback, prediction rating, and progress dashboard router."""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.api.deps import get_db, get_current_user
from app.core.reasons import (
    CATALOGUE_VERSION,
    KIND_LABELS,
    VALID_KINDS,
    get_reason,
    map_legacy_reason,
    resolve_and_validate_reason,
)
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
from app.ml.predictor import MLPredictor, FeatureMismatchError
from app.ml.explainer import explain_text

logger = logging.getLogger("tradezen.decisions")
router = APIRouter(tags=["decisions & progress"])

MIN_KIND_SAMPLE_SIZE = 5
MIN_REASON_SAMPLE_SIZE = 3


def _is_attempt_disciplined(att: Attempt) -> int:
    """Determines whether an attempt was disciplined (1) or a mistake/rule-break (0)."""
    lbl = att.prediction.label if att.prediction else "disciplined"
    if lbl == "disciplined":
        return 1
    if lbl in ("rules_only", "unavailable"):
        feats = (att.prediction.features if att.prediction else None) or {}
        violated = any(
            float(feats.get(k, 0.0)) > 0.0
            for k in (
                "rule_violates_max_trades",
                "rule_violates_position_size",
                "rule_violates_averaging_down",
                "consistency_has_contradiction",
            )
        )
        return 0 if violated else 1
    return 0


@router.post("/decisions", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_decision(
    decision_in: AttemptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submits a trading decision on a scenario and returns three-part feedback:

    1. User's Rules check (including plain-code consistency checks)
    2. Pattern classification (trained model / SHAP template, or rules-only fallback)
    3. User's personal history
    """
    # Validate action-reason pair upfront -> friendly 422 on invalid pair
    try:
        resolved_reason = resolve_and_validate_reason(
            action=decision_in.action,
            reason_code=decision_in.reason_code,
            reason_text=decision_in.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    resolved_code = resolved_reason.code
    resolved_kind = resolved_reason.kind
    display_reason = resolved_reason.label

    scenario = db.query(Scenario).filter(Scenario.id == decision_in.scenario_id).first()
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    active_rule = (
        db.query(Rule)
        .filter(Rule.user_id == current_user.id, Rule.is_current.is_(True))
        .first()
    )
    if not active_rule:
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

    # 1. Deterministic Rule check & plain-code consistency checks
    rules_feedback = check_user_rules(
        rule=active_rule,
        scenario=scenario,
        decision=decision_in,
        user_trades_today=trades_today,
        resolved_reason_code=resolved_code,
        resolved_reason_kind=resolved_kind,
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
            "label": (
                a.prediction.label
                if a.prediction and a.prediction.label not in ("rules_only", "unavailable")
                else ("disciplined" if _is_attempt_disciplined(a) else "averaging_down")
            ),
            "decision_seconds": a.decision_seconds,
            "size": a.size,
            "action": a.action,
            "reason": a.reason,
            "reason_code": a.reason_code,
        }
        for a in reversed(past_attempts)
    ]
    history_features = compute_history_features(prior_decisions)

    # 3. Decision-time feature vector
    feature_vec = extract_feature_vector(
        action=decision_in.action,
        size=decision_in.size,
        reason=display_reason,
        reason_code=resolved_code,
        reason_kind=resolved_kind,
        decision_seconds=decision_in.decision_seconds,
        chart_viewed=decision_in.chart_viewed,
        scenario_drop_pct=scenario.drop_pct,
        scenario_current_price=scenario.current_price,
        scenario_entry_price=scenario.entry_price,
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

    # 4. ML Pattern detection & SHAP explanation (with rules-only fallback if missing/mismatched)
    try:
        predictor = MLPredictor.get_instance()
        ml_result = predictor.predict(feature_vec)
        detected_label = ml_result["label"]
        prob = ml_result["probability"]
        reasons_list = [r["feature"].replace("_", " ") for r in ml_result["reasons"]]
        explanation = explain_text(feature_vec, ml_result["reasons"], predicted_label=detected_label)
        model_version = ml_result["model_version"]
        pattern_available = True
    except (FileNotFoundError, FeatureMismatchError) as exc:
        logger.warning("ML model missing or feature mismatch; falling back to rules-only: %s", exc)
        detected_label = "rules_only"
        prob = 0.0
        reasons_list = []
        explanation = "pattern feedback not available yet"
        model_version = "rules-only"
        pattern_available = False
    except Exception as exc:
        logger.warning("ML inference fallback used: %s", exc)
        detected_label = "rules_only"
        prob = 0.0
        reasons_list = []
        explanation = "pattern feedback not available yet"
        model_version = "rules-only"
        pattern_available = False

    pattern_feedback = PatternResult(
        label=detected_label,
        probability=prob,
        reasons=reasons_list,
        explanation=explanation,
        available=pattern_available,
    )

    # 5. Personal History feedback (past 10 decisions)
    if len(past_attempts) < 3:
        history_feedback = (
            f"Early progress: {len(past_attempts)} decision(s) recorded so far. "
            "Continue practicing to unlock personalized behavioral trend analysis."
        )
    else:
        mistake_cnt = int(history_features["history_mistake_count"])
        history_feedback = f"In your last {len(past_attempts)} decisions: {mistake_cnt} pattern deviation(s) noted."

    # Save Attempt
    clean_note = decision_in.note.strip() if decision_in.note and decision_in.note.strip() else None
    attempt = Attempt(
        user_id=current_user.id,
        scenario_id=decision_in.scenario_id,
        attempt_no=attempt_no,
        actor_type="human",
        action=decision_in.action,
        size=decision_in.size,
        reason=display_reason,
        reason_code=resolved_code,
        reason_kind=resolved_kind,
        catalogue_version=CATALOGUE_VERSION,
        migrated=False,
        note=clean_note,
        rule_version=active_rule.version,
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
        reason_code=resolved_code,
        reason_kind=resolved_kind,
        catalogue_version=CATALOGUE_VERSION,
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


def _build_reason_analytics(attempts: List[Attempt]) -> Dict[str, Any]:
    """Computes reason-kind breakdown and reason-vs-outcome summaries with sample gating."""
    total = len(attempts)
    kind_counts: Dict[str, int] = {k: 0 for k in VALID_KINDS}
    reason_groups: Dict[tuple, Dict[str, Any]] = {}

    for att in attempts:
        r_code = att.reason_code
        r_kind = att.reason_kind
        if not r_code or not r_kind:
            mapped = map_legacy_reason(att.reason, att.action)
            r_code = r_code or mapped.code
            r_kind = r_kind or mapped.kind

        if r_kind not in kind_counts:
            r_kind = "unsure"
        kind_counts[r_kind] += 1

        is_disc = _is_attempt_disciplined(att)
        rdef = get_reason(r_code)
        r_label = rdef.label if rdef else (att.reason or r_code)

        key = (r_code, att.action)
        grp = reason_groups.get(key)
        if grp is None:
            grp = {
                "reason_code": r_code,
                "reason_label": r_label,
                "reason_kind": r_kind,
                "action": att.action,
                "count": 0,
                "disciplined_count": 0,
                "outcomes_10m": [],
                "outcomes_30m": [],
                "action_outcomes_10m": [],
            }
            reason_groups[key] = grp

        grp["count"] += 1
        grp["disciplined_count"] += is_disc

        sc = att.scenario
        if sc is not None:
            if sc.outcome_10m is not None:
                o10 = float(sc.outcome_10m)
                grp["outcomes_10m"].append(o10)
                directional = -o10 if att.action == "sell" else o10
                grp["action_outcomes_10m"].append(directional)
            if sc.outcome_30m is not None:
                grp["outcomes_30m"].append(float(sc.outcome_30m))

    kind_items = [
        {
            "kind": k,
            "label": KIND_LABELS.get(k, k.title()),
            "count": kind_counts[k],
            "pct": round((kind_counts[k] / total) * 100.0, 1) if total > 0 else 0.0,
        }
        for k in VALID_KINDS
    ]

    reason_vs_outcome_items: List[Dict[str, Any]] = []
    for grp in sorted(reason_groups.values(), key=lambda g: g["count"], reverse=True):
        cnt = grp["count"]
        meets_min = cnt >= MIN_REASON_SAMPLE_SIZE
        o10_list = grp["outcomes_10m"]
        o30_list = grp["outcomes_30m"]
        act_o10_list = grp["action_outcomes_10m"]

        reason_vs_outcome_items.append({
            "reason_code": grp["reason_code"],
            "reason_label": grp["reason_label"],
            "reason_kind": grp["reason_kind"],
            "action": grp["action"],
            "count": cnt,
            "min_sample_size": MIN_REASON_SAMPLE_SIZE,
            "meets_min_sample": meets_min,
            "disciplined_pct": round((grp["disciplined_count"] / cnt) * 100.0, 1) if meets_min else None,
            "outcome_sample_count": len(o10_list),
            "avg_outcome_10m": (
                round(sum(o10_list) / len(o10_list), 2)
                if meets_min and len(o10_list) >= MIN_REASON_SAMPLE_SIZE
                else None
            ),
            "avg_outcome_30m": (
                round(sum(o30_list) / len(o30_list), 2)
                if meets_min and len(o30_list) >= MIN_REASON_SAMPLE_SIZE
                else None
            ),
            "avg_action_outcome_10m": (
                round(sum(act_o10_list) / len(act_o10_list), 2)
                if meets_min and len(act_o10_list) >= MIN_REASON_SAMPLE_SIZE
                else None
            ),
        })

    return {
        "reason_kind_breakdown": {
            "total_decisions": total,
            "min_sample_size": MIN_KIND_SAMPLE_SIZE,
            "has_enough_data": total >= MIN_KIND_SAMPLE_SIZE,
            "data_notice": "sufficient data" if total >= MIN_KIND_SAMPLE_SIZE else "not enough data yet",
            "items": kind_items,
        },
        "reason_vs_outcome": {
            "min_sample_size": MIN_REASON_SAMPLE_SIZE,
            "has_enough_data": any(item["meets_min_sample"] for item in reason_vs_outcome_items),
            "items": reason_vs_outcome_items,
        },
    }


@router.get("/progress/dashboard")
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculates comprehensive dashboard metrics including reason-kind and reason-vs-outcome."""
    current_season = getattr(current_user, "current_season", 1)

    attempts = (
        db.query(Attempt)
        .options(joinedload(Attempt.prediction), joinedload(Attempt.scenario))
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
        empty_reason_analytics = _build_reason_analytics([])
        return {
            "status": "empty",
            "message": "No decisions yet. Play your first practice scenario to start tracking progress!",
            "total_decisions": 0,
            "season": current_season,
            "has_enough_data": False,
            "data_notice": "not enough data yet",
            **empty_reason_analytics,
        }

    attempt1_list = [a for a in attempts if a.attempt_no == 1]
    revisions_list = [a for a in attempts if a.attempt_no > 1]

    scenario_attempts: Dict[int, List[Attempt]] = {}
    for a in attempts:
        scenario_attempts.setdefault(a.scenario_id, []).append(a)

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
        "rules_only": "Rules Evaluated",
    }

    disciplined_count = 0
    timeline: List[Dict[str, Any]] = []
    rolling_scores: List[Dict[str, Any]] = []
    recent_window: List[int] = []

    for idx, att in enumerate(attempts, start=1):
        lbl = att.prediction.label if att.prediction else "disciplined"
        is_disc = _is_attempt_disciplined(att)
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
            "reason_code": att.reason_code,
            "reason_kind": att.reason_kind,
        })

        rolling_scores.append({
            "trade_number": idx,
            "score": rolling_score,
            "date": att.created_at.strftime("%H:%M") if att.created_at else f"#{idx}",
        })

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

    improved_scenarios = 0
    scenarios_revised = 0
    for sc_atts in scenario_attempts.values():
        if len(sc_atts) > 1:
            scenarios_revised += 1
            if _is_attempt_disciplined(sc_atts[0]) == 0 and _is_attempt_disciplined(sc_atts[-1]) == 1:
                improved_scenarios += 1

    improvement_pct = round((improved_scenarios / max(1, scenarios_revised)) * 100, 1) if scenarios_revised > 0 else 0.0
    rule_compliance_pct = round((disciplined_count / max(1, total_decisions)) * 100, 1)
    discipline_score = rule_compliance_pct

    has_enough_data = total_decisions >= 10
    reason_analytics = _build_reason_analytics(attempts)

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
        **reason_analytics,
    }
