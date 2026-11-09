"""TradeZen unified settings module.

Loads all configuration strictly from environment variables and .env file.
No secrets are stored in code.
Uses pathlib for cross-platform relative path resolution.
"""

from pathlib import Path
from typing import Any, List, Optional, Union
from pydantic import Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cross-platform project root resolution using pathlib
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def mask_token(token: Optional[str]) -> str:
    """Safely masks sensitive tokens for logging and debug output.

    Never exposes secret token contents.
    """
    if not token:
        return "<none>"
    t = str(token).strip()
    if len(t) <= 8:
        return "***"
    return f"{t[:4]}...{t[-4:]}"


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    # Project Information & Paths
    PROJECT_NAME: str = "TradeZen Scenario Coach"
    PROJECT_ROOT: Path = PROJECT_ROOT
    ENVIRONMENT: str = "development"

    # PostgreSQL Database URL only
    DATABASE_URL: str

    # Security & Tokens (Secrets - no defaults in code)
    JWT_SECRET: str = Field(..., repr=False)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Market Data (Upstox Analytics Token with backward-compatible alias)
    UPSTOX_ANALYTICS_TOKEN: str = Field(
        ...,
        validation_alias=AliasChoices("UPSTOX_ANALYTICS_TOKEN", "ANALYTICS_TOKEN"),
        repr=False,
    )
    USE_SAMPLE_DATA: bool = False

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

    def __init__(self, **values: Any):
        if "UPSTOX_ANALYTICS_TOKEN" not in values and "ANALYTICS_TOKEN" in values:
            values["UPSTOX_ANALYTICS_TOKEN"] = values.pop("ANALYTICS_TOKEN")
        super().__init__(**values)

    @field_validator("UPSTOX_ANALYTICS_TOKEN", mode="before")
    @classmethod
    def validate_upstox_analytics_token(cls, v: Any) -> str:
        """Validates that a non-empty Upstox Analytics Token is supplied."""
        if v is None or not str(v).strip():
            raise ValueError(
                "UPSTOX_ANALYTICS_TOKEN is missing. Please provide a valid Upstox Analytics Token "
                "in your .env file or environment variables under UPSTOX_ANALYTICS_TOKEN (or ANALYTICS_TOKEN)."
            )
        return str(v).strip()

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

    def get_masked_analytics_token(self) -> str:
        """Returns the masked version of the Upstox Analytics Token."""
        return mask_token(self.UPSTOX_ANALYTICS_TOKEN)

    def __repr__(self) -> str:
        return (
            f"Settings(PROJECT_NAME='{self.PROJECT_NAME}', "
            f"ENVIRONMENT='{self.ENVIRONMENT}', "
            f"UPSTOX_ANALYTICS_TOKEN='{self.get_masked_analytics_token()}', "
            f"PORT={self.PORT}, "
            f"HOST='{self.HOST}')"
        )

    def __str__(self) -> str:
        return self.__repr__()


# Singleton instance
settings = Settings()
