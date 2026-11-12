"""Reasons catalogue router: returns action-filtered decision reasons."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.reasons import (
    CATALOGUE_VERSION,
    get_reasons_for_action,
    normalize_action,
    sync_reasons_table,
)
from app.models.reason import ScnReason
from app.schemas.decision import ReasonItem, ReasonsResponse

router = APIRouter(prefix="/reasons", tags=["reasons"])


@router.get("", response_model=ReasonsResponse)
def list_reasons_for_action(
    action: str = Query(..., description="Trading action: buy, hold, or sell"),
    db: Session = Depends(get_db),
):
    """Returns only the reasons valid for the chosen action from the single source of truth."""
    try:
        act = normalize_action(action)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    rows = (
        db.query(ScnReason)
        .filter(
            ScnReason.action == act,
            ScnReason.catalogue_version == CATALOGUE_VERSION,
            ScnReason.is_active.is_(True),
        )
        .order_by(ScnReason.display_order.asc(), ScnReason.id.asc())
        .all()
    )

    if not rows:
        try:
            sync_reasons_table(db)
            rows = (
                db.query(ScnReason)
                .filter(
                    ScnReason.action == act,
                    ScnReason.catalogue_version == CATALOGUE_VERSION,
                    ScnReason.is_active.is_(True),
                )
                .order_by(ScnReason.display_order.asc(), ScnReason.id.asc())
                .all()
            )
        except Exception:
            rows = []

    if rows:
        items = [ReasonItem.model_validate(r) for r in rows]
    else:
        items = [ReasonItem(**r.to_dict()) for r in get_reasons_for_action(act)]

    return ReasonsResponse(
        catalogue_version=CATALOGUE_VERSION,
        action=act,
        reasons=items,
    )
