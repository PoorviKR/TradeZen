"""Tests for deterministic rule checking service."""

import pytest
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.schemas.decision import AttemptCreate
from app.services.rule_checker import check_user_rules


@pytest.fixture
def base_rule() -> Rule:
    return Rule(
        user_id=1,
        version=1,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        no_averaging_down=True,
        max_position_pct=20.0,
        practice_capital=100000.0,
        is_current=True,
    )


@pytest.fixture
def loss_scenario() -> Scenario:
    return Scenario(
        symbol="ANON_LOSS",
        event_type="drop",
        entry_price=100.0,
        current_price=98.0,
        drop_pct=2.0,
        candles=[],
        trades_today=1,
        last_trade_was_loss=False,
    )


@pytest.fixture
def gain_scenario() -> Scenario:
    return Scenario(
        symbol="ANON_GAIN",
        event_type="spike",
        entry_price=100.0,
        current_price=103.0,
        drop_pct=0.0,
        candles=[],
        trades_today=1,
        last_trade_was_loss=False,
    )


def test_rule_checker_clean_pass(base_rule, loss_scenario):
    """Test a disciplined sell decision when stop-loss is reached."""
    decision = AttemptCreate(
        scenario_id=1,
        action="sell",
        size=10000.0,
        reason="Followed my rule",
        decision_seconds=12.0,
    )
    result = check_user_rules(base_rule, loss_scenario, decision, user_trades_today=3)
    assert result.passed is True
    assert len(result.violations) == 0
    assert "disciplined" in result.rule_summary.lower()


def test_rule_checker_averaging_down_violation(base_rule, loss_scenario):
    """Test buying more while in a loss triggers averaging down violation."""
    decision = AttemptCreate(
        scenario_id=1,
        action="buy",
        size=10000.0,
        reason="Recover loss",
        decision_seconds=4.0,
    )
    result = check_user_rules(base_rule, loss_scenario, decision, user_trades_today=2)
    assert result.passed is False
    assert any("Averaging Down" in v for v in result.violations)


def test_rule_checker_overtrading_violation(base_rule, gain_scenario):
    """Test exceeding max trades per day triggers overtrading violation."""
    decision = AttemptCreate(
        scenario_id=1,
        action="sell",
        size=10000.0,
        reason="Did analysis",
        decision_seconds=20.0,
    )
    # Trade 6 exceeds limit of 5
    result = check_user_rules(base_rule, gain_scenario, decision, user_trades_today=6)
    assert result.passed is False
    assert any("daily trade limit" in v for v in result.violations)


def test_rule_checker_oversized_position_violation(base_rule, gain_scenario):
    """Test sizing beyond max position percentage triggers violation."""
    # 25,000 > 20% of 100,000 (20,000)
    decision = AttemptCreate(
        scenario_id=1,
        action="buy",
        size=25000.0,
        reason="FOMO",
        decision_seconds=3.0,
    )
    result = check_user_rules(base_rule, gain_scenario, decision, user_trades_today=2)
    assert result.passed is False
    assert any("Oversized position" in v for v in result.violations)
