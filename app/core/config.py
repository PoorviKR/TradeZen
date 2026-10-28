"""TradeZen unified settings module.

Loads all configuration strictly from environment variables and .env file.
No secrets are stored in code.
Uses pathlib for cross-platform relative path resolution.
"""

from pathlib import Path
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cross-platform project root resolution using pathlib
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    # Project Information & Paths
    PROJECT_NAME: str = "TradeZen Scenario Coach"
    PROJECT_ROOT: Path = PROJECT_ROOT
    ENVIRONMENT: str = "development"

    # PostgreSQL Database URL only
    DATABASE_URL: str

    # Security & Tokens (Secrets - no defaults in code)
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Market Data
    UPSTOX_ANALYTICS_TOKEN: str

    # API Routing & Networking
    API_BASE_URL: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: Union[List[str], str] = ["*"]

    # Model configuration
    model_config = SettingsConfigDict(
        env_file=ENV_PATH if ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_postgresql_only(cls, v: str) -> str:
        """Enforces that only PostgreSQL databases are allowed."""
        valid_prefixes = ("postgresql://", "postgresql+psycopg2://", "postgresql+asyncpg://")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(
                f"Invalid DATABASE_URL. PostgreSQL is the only supported database. "
                f"URL must start with postgresql:// or postgresql+psycopg2:// (received: {v.split('://')[0]}://...)"
            )
        # Ensure psycopg2-compatible dialect when postgresql:// is provided for SQLAlchemy
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Parses comma-separated origins string into list of strings."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validates that a non-empty JWT secret is provided."""
        if not v or len(v.strip()) < 8:
            raise ValueError("JWT_SECRET must be set and have a minimum length of 8 characters.")
        return v.strip()


# Singleton instance
settings = Settings()
