"""API v1 router bundle."""

from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.rules import router as rules_router
from app.api.v1.scenarios import router as scenarios_router
from app.api.v1.decisions import router as decisions_router
from app.api.v1.health import router as health_router
from app.api.v1.reasons import router as reasons_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(rules_router)
api_router.include_router(scenarios_router)
api_router.include_router(decisions_router)
api_router.include_router(reasons_router)
