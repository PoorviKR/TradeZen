"""Deterministic rule checker and plain-code reason consistency service for TradeZen.

Rules and consistency checks are always evaluated in plain code (never by an LLM or ML model).
"""

from typing import Dict, List, Optional, Tuple
from app.core.reasons import map_legacy_reason, get_reason
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.schemas.decision import AttemptCreate, RuleCheckResult


CONSISTENCY_FLAG_NAMES: Tuple[str, ...] = (
    "consistency_sell_stop_not_hit",
    "consistency_hold_past_stop",
    "consistency_add_winner_in_loss",
    "consistency_averaging_against_rule",
    "consistency_plan_contradicts_numbers",
    "consistency_has_contradiction",
)


def compute_consistency_checks(
    action: str,
    size: float,
    reason_code: Optional[str],
    reason_kind: Optional[str],
    entry_price: float,
    current_price: float,
    drop_pct: float,
    user_trades_today: int,
    stop_loss_pct: float,
    max_trades_per_day: int,
    max_position_pct: float,
    no_averaging_down: bool,
    practice_capital: float,
    rule_version: Optional[int] = None,
) -> Tuple[Dict[str, bool], List[str]]:
    """Evaluates plain-code consistency between the stated reason, scenario numbers, and rule version.

    Shared by both deterministic Rules feedback and ML feature extraction.
    """
    act = (action or "").strip().lower()
    code = (reason_code or "").strip().upper()
    kind = (reason_kind or "").strip().lower()
    if not kind and code:
        rdef = get_reason(code)
        kind = rdef.kind if rdef else ""

    safe_capital = max(1000.0, float(practice_capital or 100000.0))
    safe_max_pos_pct = max(1.0, min(100.0, float(max_position_pct or 20.0)))
    safe_max_trades = max(1, int(max_trades_per_day or 5))
    safe_stop_loss = max(0.01, float(stop_loss_pct or 2.0))

    entry_p = float(entry_price or 0.0)
    curr_p = float(current_price or 0.0)
    drop_p = float(drop_pct or 0.0)

    if entry_p > 0 and curr_p > 0:
        overall_drop_pct = ((entry_p - curr_p) / entry_p) * 100.0
    else:
        overall_drop_pct = drop_p

    effective_loss_pct = max(drop_p, overall_drop_pct) if drop_p > 0 else overall_drop_pct
    is_loss_position = (entry_p > 0 and curr_p > 0 and curr_p < entry_p) or (drop_p > 0.5)
    stop_reached = effective_loss_pct >= safe_stop_loss
    loss_past_stop = effective_loss_pct > safe_stop_loss

    size_pct = (float(size) / safe_capital) * 100.0
    violates_max_trades = user_trades_today > safe_max_trades
    violates_position_size = size_pct > safe_max_pos_pct

    ver_tag = f"Rule v{rule_version}" if rule_version is not None else "Active Rule"
    warnings: List[str] = []

    sell_stop_not_hit = (code == "SELL_STOP_HIT") and (not stop_reached)
    if sell_stop_not_hit:
        warnings.append(
            f"Consistency check ({ver_tag}): You chose 'My stop-loss was hit' (SELL_STOP_HIT), "
            f"but the price move ({effective_loss_pct:.2f}%) had not reached your {safe_stop_loss:.1f}% stop-loss."
        )

    hold_past_stop = (code == "HOLD_PLAN_INTACT") and loss_past_stop
    if hold_past_stop:
        warnings.append(
            f"Consistency check ({ver_tag}): You chose 'Plan intact, stop not hit' (HOLD_PLAN_INTACT), "
            f"but the loss ({effective_loss_pct:.2f}%) is already past your {safe_stop_loss:.1f}% stop-loss."
        )

    add_winner_in_loss = (code == "BUY_ADD_WINNER") and is_loss_position
    if add_winner_in_loss:
        pnl_pct = -overall_drop_pct
        warnings.append(
            f"Consistency check ({ver_tag}): You chose 'Adding to a winning trade' (BUY_ADD_WINNER), "
            f"but this position is currently in a loss ({pnl_pct:+.2f}%)."
        )

    averaging_against_rule = (code in ("BUY_BALANCE_LOSS", "BUY_RECOVER_LOSS")) and bool(no_averaging_down)
    if averaging_against_rule:
        warnings.append(
            f"Consistency check ({ver_tag}): Reason '{code}' cites averaging down or recovering a loss, "
            f"which conflicts with your 'No Averaging Down' rule."
        )

    # Check any other plan-kind reason contradicting scenario numbers or rule limits
    plan_contradiction = sell_stop_not_hit or hold_past_stop or add_winner_in_loss
    if kind == "plan":
        if code == "HOLD_LET_PROFIT_RUN" and is_loss_position:
            plan_contradiction = True
            warnings.append(
                f"Consistency check ({ver_tag}): You chose 'Letting a winning trade run' (HOLD_LET_PROFIT_RUN), "
                f"but the scenario is currently in a loss."
            )
        elif code == "SELL_TARGET" and is_loss_position:
            plan_contradiction = True
            warnings.append(
                f"Consistency check ({ver_tag}): You chose 'My profit target was hit' (SELL_TARGET), "
                f"but the scenario is in a loss rather than a profit."
            )
        elif code == "BUY_PLANNED" and (
            violates_max_trades or violates_position_size or (bool(no_averaging_down) and is_loss_position)
        ):
            plan_contradiction = True
            warnings.append(
                f"Consistency check ({ver_tag}): You chose 'Matched my entry plan' (BUY_PLANNED), "
                f"but the scenario or trade sizing contradicts your rule limits."
            )
        elif act == "buy" and (violates_max_trades or violates_position_size or (bool(no_averaging_down) and is_loss_position)):
            plan_contradiction = True
            if not add_winner_in_loss:
                warnings.append(
                    f"Consistency check ({ver_tag}): Your plan-based buy reason contradicts your active rule constraints."
                )

    has_contradiction = (
        sell_stop_not_hit
        or hold_past_stop
        or add_winner_in_loss
        or averaging_against_rule
        or plan_contradiction
    )

    flags = {
        "consistency_sell_stop_not_hit": sell_stop_not_hit,
        "consistency_hold_past_stop": hold_past_stop,
        "consistency_add_winner_in_loss": add_winner_in_loss,
        "consistency_averaging_against_rule": averaging_against_rule,
        "consistency_plan_contradicts_numbers": plan_contradiction,
        "consistency_has_contradiction": has_contradiction,
    }
    return flags, warnings


def check_user_rules(
    rule: Rule,
    scenario: Scenario,
    decision: AttemptCreate,
    user_trades_today: int,
    resolved_reason_code: Optional[str] = None,
    resolved_reason_kind: Optional[str] = None,
) -> RuleCheckResult:
    """Compares user decision and stated reason against the rule version that applied then.

    Safely handles edge cases including zero/negative capital, non-positive prices,
    and extreme values.
    """
    violations: List[str] = []

    rule_ver = getattr(rule, "version", 1)
    safe_capital = max(1000.0, float(getattr(rule, "practice_capital", 100000.0) or 100000.0))
    safe_max_pos_pct = max(1.0, min(100.0, float(getattr(rule, "max_position_pct", 20.0) or 20.0)))
    safe_max_trades = max(1, int(getattr(rule, "max_trades_per_day", 5) or 5))
    safe_stop_loss = max(0.01, float(getattr(rule, "stop_loss_pct", 2.0) or 2.0))
    no_avg_down = bool(getattr(rule, "no_averaging_down", True))

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
    entry_p = float(getattr(scenario, "entry_price", 0.0) or 0.0)
    curr_p = float(getattr(scenario, "current_price", 0.0) or 0.0)
    drop_p = float(getattr(scenario, "drop_pct", 0.0) or 0.0)

    if no_avg_down and decision.action == "buy":
        is_loss_position = (entry_p > 0 and curr_p > 0 and curr_p < entry_p) or (drop_p > 0.5)
        if is_loss_position:
            violations.append(
                "Violated 'No Averaging Down': bought additional shares while current position is in a loss."
            )

    # 4. Plain-code reason consistency checks judged by the rule version that applied then
    code = resolved_reason_code or getattr(decision, "reason_code", None)
    kind = resolved_reason_kind
    if not code:
        mapped = map_legacy_reason(getattr(decision, "reason", None), decision.action)
        code = mapped.code
        kind = mapped.kind
    elif not kind:
        rdef = get_reason(code)
        kind = rdef.kind if rdef else ""

    consistency_flags, consistency_warnings = compute_consistency_checks(
        action=decision.action,
        size=decision.size,
        reason_code=code,
        reason_kind=kind,
        entry_price=entry_p,
        current_price=curr_p,
        drop_pct=drop_p,
        user_trades_today=user_trades_today,
        stop_loss_pct=safe_stop_loss,
        max_trades_per_day=safe_max_trades,
        max_position_pct=safe_max_pos_pct,
        no_averaging_down=no_avg_down,
        practice_capital=safe_capital,
        rule_version=rule_ver,
    )
    violations.extend(consistency_warnings)

    passed = len(violations) == 0
    summary = (
        f"All trading rules respected (Rule v{rule_ver})! Disciplined execution."
        if passed
        else f"Detected {len(violations)} rule/consistency issue(s) under Rule v{rule_ver}."
    )

    return RuleCheckResult(
        passed=passed,
        violations=violations,
        rule_summary=summary,
        rule_version=rule_ver,
        consistency_warnings=consistency_warnings,
        consistency_flags=consistency_flags,
    )
