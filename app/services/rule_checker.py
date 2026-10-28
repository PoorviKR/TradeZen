"""Deterministic rule checker service for TradeZen.

Rules are always evaluated in plain code (never by an LLM or ML model).
"""

from typing import List, Tuple
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.schemas.decision import AttemptCreate, RuleCheckResult


def check_user_rules(
    rule: Rule,
    scenario: Scenario,
    decision: AttemptCreate,
    user_trades_today: int,
) -> RuleCheckResult:
    """Compares user decision against the user's active rules deterministically."""
    violations: List[str] = []

    # 1. Daily trades limit check
    if user_trades_today > rule.max_trades_per_day:
        violations.append(
            f"Exceeded daily trade limit: {user_trades_today} trades today (your limit is {rule.max_trades_per_day})."
        )

    # 2. Position size check
    max_allowed_size = (rule.max_position_pct / 100.0) * rule.practice_capital
    if decision.size > max_allowed_size:
        violations.append(
            f"Oversized position: ₹{decision.size:,.2f} exceeds your {rule.max_position_pct}% limit (₹{max_allowed_size:,.2f})."
        )

    # 3. Averaging down check (buying more while in an open loss)
    if rule.no_averaging_down and decision.action == "buy":
        if scenario.current_price < scenario.entry_price or scenario.drop_pct > 0.5:
            violations.append(
                "Violated 'No Averaging Down': bought additional shares while current position is in a loss."
            )

    passed = len(violations) == 0
    summary = (
        "All trading rules respected! Disciplined execution."
        if passed
        else f"Detected {len(violations)} rule violation(s)."
    )

    return RuleCheckResult(passed=passed, violations=violations, rule_summary=summary)
