"""Scenarios router: serving unseen scenarios and reveals."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.scenario import Scenario
from app.models.decision import Attempt
from app.schemas.scenario import ScenarioPublicResponse, ScenarioRevealResponse

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("/next", response_model=List[ScenarioPublicResponse])
def get_next_scenarios(
    limit: int = 15,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns 10-20 active scenarios that the logged-in user has not attempted yet.

    Anonymizes the symbol and date to prevent hindsight bias.
    """
    # Extract scenario IDs already attempted by current user
    seen_ids = [
        r[0]
        for r in db.query(Attempt.scenario_id)
        .filter(Attempt.user_id == current_user.id)
        .distinct()
        .all()
    ]

    query = db.query(Scenario).filter(Scenario.active.is_(True))
    if seen_ids:
        query = query.filter(~Scenario.id.in_(seen_ids))

    effective_limit = max(10, min(limit, 20))
    unseen_scenarios = (
        query.order_by(func.random())
        .limit(effective_limit)
        .all()
    )

    return unseen_scenarios


@router.get("/{scenario_id}/reveal", response_model=ScenarioRevealResponse)
def get_scenario_reveal(
    scenario_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reveals what happened after the decision point (2, 5, 10, 30 minutes).

    Only accessible after user has made at least one attempt.
    """
    attempt = (
        db.query(Attempt)
        .filter(Attempt.user_id == current_user.id, Attempt.scenario_id == scenario_id)
        .first()
    )
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must submit a decision before viewing the outcome reveal.",
        )

    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    return scenario
