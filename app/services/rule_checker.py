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
    """Compares user decision against the user's active rules deterministically.

    Safely handles edge cases including zero/negative capital, non-positive prices,
    and extreme values.
    """
    violations: List[str] = []

    # Safe defaults for numerical stability
    safe_capital = max(1000.0, float(getattr(rule, "practice_capital", 100000.0) or 100000.0))
    safe_max_pos_pct = max(1.0, min(100.0, float(getattr(rule, "max_position_pct", 20.0) or 20.0)))
    safe_max_trades = max(1, int(getattr(rule, "max_trades_per_day", 5) or 5))

    # 1. Daily trades limit check
    if user_trades_today > safe_max_trades:
        violations.append(
            f"Exceeded daily trade limit: {user_trades_today} trades today (your limit is {safe_max_trades})."
        )

    # 2. Position size check
    max_allowed_size = (safe_max_pos_pct / 100.0) * safe_capital
    if decision.size > max_allowed_size:
        violations.append(
            f"Oversized position: ₹{decision.size:,.2f} exceeds your {safe_max_pos_pct}% limit (₹{max_allowed_size:,.2f})."
        )

    # 3. Averaging down check (buying more while in an open loss)
    if getattr(rule, "no_averaging_down", True) and decision.action == "buy":
        entry_p = float(getattr(scenario, "entry_price", 0.0) or 0.0)
        curr_p = float(getattr(scenario, "current_price", 0.0) or 0.0)
        drop_p = float(getattr(scenario, "drop_pct", 0.0) or 0.0)

        # Check if in a loss
        is_loss_position = False
        if entry_p > 0 and curr_p > 0 and curr_p < entry_p:
            is_loss_position = True
        elif drop_p > 0.5:
            is_loss_position = True

        if is_loss_position:
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
