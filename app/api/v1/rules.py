"""User rules router: view, create, edit with versioning."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.rule import Rule
from app.schemas.rule import RuleCreate, RuleResponse

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/current", response_model=Optional[RuleResponse])
def get_current_rule(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches the current active trading rule for the logged-in user."""
    rule = (
        db.query(Rule)
        .filter(Rule.user_id == current_user.id, Rule.is_current.is_(True))
        .first()
    )
    return rule


@router.get("/history", response_model=List[RuleResponse])
def get_rule_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches all versions of trading rules for the logged-in user."""
    rules = (
        db.query(Rule)
        .filter(Rule.user_id == current_user.id)
        .order_by(Rule.version.desc())
        .all()
    )
    return rules


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def set_rules(
    rule_in: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets new rules or increments version history for the logged-in user."""
    # Find active rule and mark inactive
    latest_rule = (
        db.query(Rule)
        .filter(Rule.user_id == current_user.id)
        .order_by(Rule.version.desc())
        .first()
    )

    new_version = 1
    if latest_rule:
        new_version = latest_rule.version + 1
        # Deactivate all previous versions
        db.query(Rule).filter(Rule.user_id == current_user.id).update(
            {"is_current": False}
        )

    new_rule = Rule(
        user_id=current_user.id,
        version=new_version,
        stop_loss_pct=rule_in.stop_loss_pct,
        max_trades_per_day=rule_in.max_trades_per_day,
        no_averaging_down=rule_in.no_averaging_down,
        max_position_pct=rule_in.max_position_pct,
        practice_capital=rule_in.practice_capital,
        is_current=True,
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule
