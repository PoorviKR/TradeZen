"""Main FastAPI application entry point for TradeZen Scenario Coach."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1 import api_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Educational Behavioral Scenario Coach for Retail Traders",
    version="0.1.0",
    docs_url=f"{settings.API_BASE_URL}/docs",
    openapi_url=f"{settings.API_BASE_URL}/openapi.json",
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
