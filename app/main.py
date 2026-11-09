"""Main FastAPI application entry point for TradeZen Scenario Coach."""

import logging
import threading
from datetime import date
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from app.core.config import settings
from app.api.v1 import api_router
from app.db.session import SessionLocal
from app.models.scenario import Scenario
from app.services.upstox_client import UpstoxClient
from app.jobs.refresh_scenarios import refresh_scenarios

logger = logging.getLogger("tradezen")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Educational Behavioral Scenario Coach for Retail Traders",
    version="0.1.0",
    docs_url=f"{settings.API_BASE_URL}/docs",
    openapi_url=f"{settings.API_BASE_URL}/openapi.json",
)

# Helpful database exception handlers
@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    logger.error("Database connection failure: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Database connection failed: Could not connect to PostgreSQL on port 5432. "
                "Please make sure PostgreSQL is running (e.g. run 'docker compose up -d' or start your PostgreSQL service)."
            )
        },
    )

@app.exception_handler(ProgrammingError)
async def programming_error_handler(request: Request, exc: ProgrammingError):
    logger.error("Database schema error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Database tables not found. Please run 'python -m app.db.init_db' to initialize the database tables."
            )
        },
    )

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    logger.error("Database error: %s", exc)
    error_msg = str(exc.orig) if hasattr(exc, "orig") else str(exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Database error: {error_msg}"},
    )

# CORS configuration supporting network/Wi-Fi devices and web clients
origins = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if "*" not in origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers under configured API base URL (e.g. /api/v1)
app.include_router(api_router, prefix=settings.API_BASE_URL)


def check_and_catch_up_scenarios():
    """Checks if the scenario pool is behind and triggers background catch-up if needed."""
    def _worker():
        try:
            with SessionLocal() as db:
                client = UpstoxClient()
                today = date.today()
                recent_days = client.get_trading_days(today, 1)
                last_trading_day = recent_days[-1]

                # Check active scenario count
                active_count = (
                    db.query(func.count(Scenario.id))
                    .filter(Scenario.active.is_(True))
                    .scalar()
                    or 0
                )
                if active_count < 200:
                    logger.info(
                        "Scenario pool is behind (active scenarios: %d < 200). Running background catch-up...",
                        active_count,
                    )
                    refresh_scenarios(target_date=last_trading_day, db_session=db, client=client)
                    logger.info("Background scenario pool catch-up completed.")
                else:
                    logger.info("Scenario pool is up to date with %d active scenarios.", active_count)
        except Exception as exc:
            logger.info("Background scenario catch-up check skipped: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True, name="scenario-catchup-worker")
    thread.start()


@app.on_event("startup")
def on_startup():
    """Application startup tasks: preloads ML predictor and runs non-blocking pool catch-up if behind."""
    try:
        from app.ml.predictor import MLPredictor
        MLPredictor.get_instance()
    except Exception as exc:
        logger.info("ML predictor startup preload note: %s", exc)

    if settings.ENVIRONMENT != "test":
        check_and_catch_up_scenarios()


@app.get("/")
def root():
    """Root entrypoint returning application metadata and status."""
    return {
        "app": settings.PROJECT_NAME,
        "status": "online",
        "api_docs": f"{settings.API_BASE_URL}/docs",
        "health": f"{settings.API_BASE_URL}/health",
    }


def start_server():
    """Starts the uvicorn ASGI server listening on all network interfaces."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=(settings.ENVIRONMENT == "development"),
    )


if __name__ == "__main__":
    start_server()
