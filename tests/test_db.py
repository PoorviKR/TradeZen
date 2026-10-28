"""Tests for database models, metadata, and relations."""

import pytest
from app.db.base import Base
from app.models.user import User
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.models.decision import Attempt, BotDecision, Prediction
from app.core.security import hash_password


def test_database_metadata_registered_tables():
    """Verify that all core tables are present in Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {"users", "rules", "scenarios", "attempts", "bot_decisions", "predictions"}
    assert expected_tables.issubset(table_names), f"Missing tables in metadata: {expected_tables - table_names}"


def test_user_cascade_deletion(db_session):
    """Verify that deleting a user cascades to rules and attempts."""
    user = User(
        email="cascade_test@example.com",
        password_hash=hash_password("Pass123!"),
        display_name="Cascade User",
    )
    db_session.add(user)
    db_session.commit()

    rule = Rule(
        user_id=user.id,
        version=1,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        no_averaging_down=True,
        max_position_pct=20.0,
        practice_capital=100000.0,
    )
    db_session.add(rule)
    db_session.commit()

    assert db_session.query(Rule).filter(Rule.user_id == user.id).count() == 1

    # Delete user
    db_session.delete(user)
    db_session.commit()

    assert db_session.query(Rule).filter(Rule.user_id == user.id).count() == 0


def test_bot_decision_creation(db_session, sample_scenario):
    """Verify bot decision simulation record creation."""
    bot_dec = BotDecision(
        scenario_id=sample_scenario.id,
        actor_type="bot",
        bot_name="Panic",
        true_label="panic_sell",
        action="sell",
        size=10000.0,
        reason="Fear",
        decision_seconds=3.2,
        features={"drop_pct": 1.0, "decision_seconds": 3.2},
    )
    db_session.add(bot_dec)
    db_session.commit()
    db_session.refresh(bot_dec)

    assert bot_dec.id is not None
    assert bot_dec.actor_type == "bot"
    assert bot_dec.true_label == "panic_sell"
