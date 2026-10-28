"""Tests for application settings and environment variable validation."""

import os
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.core.config import Settings, PROJECT_ROOT


def test_settings_loads_from_env():
    """Verify settings loads properly and uses pathlib for project root."""
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="super_secret_test_key_12345678",
        UPSTOX_ANALYTICS_TOKEN="test_token_1234",
    )
    assert isinstance(settings.PROJECT_ROOT, Path)
    assert settings.DATABASE_URL == "postgresql+psycopg2://user:pass@localhost:5432/tradezen"
    assert settings.PORT == 8000
    assert settings.HOST == "0.0.0.0"


def test_postgresql_only_enforcement():
    """Verify settings rejects SQLite, MySQL, or non-PostgreSQL URLs."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DATABASE_URL="sqlite:///test.db",
            JWT_SECRET="valid_secret_length_1234",
            UPSTOX_ANALYTICS_TOKEN="token",
        )
    assert "PostgreSQL is the only supported database" in str(exc_info.value)

    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="mysql://root:pass@localhost:3306/tradezen",
            JWT_SECRET="valid_secret_length_1234",
            UPSTOX_ANALYTICS_TOKEN="token",
        )


def test_jwt_secret_validation():
    """Verify short or empty JWT secret raises an error."""
    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
            JWT_SECRET="short",
            UPSTOX_ANALYTICS_TOKEN="token",
        )


def test_allowed_origins_parsing():
    """Verify comma-separated ALLOWED_ORIGINS string parses into a list."""
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="valid_secret_length_1234",
        UPSTOX_ANALYTICS_TOKEN="token",
        ALLOWED_ORIGINS="http://localhost:5173, http://192.168.1.50:5173",
    )
    assert settings.ALLOWED_ORIGINS == ["http://localhost:5173", "http://192.168.1.50:5173"]
