"""Pytest shared test configuration and fixtures."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure environment variables are configured for testing
os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5432/tradezen"
os.environ["JWT_SECRET"] = "test_secret_key_minimum_32_characters_long_tradezen"
os.environ["UPSTOX_ANALYTICS_TOKEN"] = "test_upstox_token"
os.environ["ALLOWED_ORIGINS"] = "*"

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models.user import User
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.core.security import hash_password, create_access_token

# In-memory database strictly for isolated unit test execution without external dependencies
TEST_SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session) -> User:
    """Creates a standard test user."""
    user = User(
        username="testuser",
        email="testuser@example.com",
        password_hash=hash_password("Password123!"),
        display_name="Test User",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user) -> dict:
    """Generates authorization headers for the test user."""
    token = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_scenario(db_session) -> Scenario:
    """Creates a sample market scenario."""
    scenario = Scenario(
        symbol="NIFTY_REL_SAMPLE",
        event_type="drop",
        entry_price=1000.0,
        current_price=990.0,
        drop_pct=1.0,
        candles=[
            {"time": 1700000000, "open": 1000.0, "high": 1005.0, "low": 989.0, "close": 990.0, "volume": 1200}
        ],
        outcome_2m=-1.5,
        outcome_5m=-2.0,
        outcome_10m=-0.5,
        outcome_30m=1.0,
        trades_today=2,
        last_trade_was_loss=True,
        active=True,
    )
    db_session.add(scenario)
    db_session.commit()
    db_session.refresh(scenario)
    return scenario

