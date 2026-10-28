"""Health check and readiness endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Basic service health check."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness probe checking database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        db_status = f"unreachable: {str(exc)}"

    return {
        "status": "ready" if db_status == "connected" else "degraded",
        "database": db_status,
        "service": settings.PROJECT_NAME,
    }
