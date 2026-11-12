"""Shared feature engineering for TradeZen bots, training, and live user inference.

Extracts decision-time features only:
- Excludes bot_name, true_label, IDs, symbols, and future outcome candles.
- Encodes reason_code (one-hot), reason_kind (one-hot), and plain-code consistency flags.
- Computes history metrics over the actor's last 10 decisions.
- Completely supports empty history.
"""

from typing import Any, Dict, List, Optional
from app.core.reasons import (
    REASON_CODES,
    VALID_KINDS,
    get_reason,
    map_legacy_reason,
)
from app.services.rule_checker import (
    CONSISTENCY_FLAG_NAMES,
    compute_consistency_checks,
)

REASON_CODE_COLUMNS: List[str] = [f"reason_code_{code}" for code in REASON_CODES]
REASON_KIND_COLUMNS: List[str] = [f"reason_kind_{kind}" for kind in VALID_KINDS]

# Canonical list of feature columns in exact ordering
FEATURE_COLUMNS: List[str] = [
    # Decision inputs
    "decision_seconds",
    "size",
    "size_pct_of_capital",
    "chart_viewed",
    "action_buy",
    "action_sell",
    "action_hold",
    # Action-dependent reason code (one-hot) and reason kind (one-hot)
    *REASON_CODE_COLUMNS,
    *REASON_KIND_COLUMNS,
    # Market & Scenario context at decision point
    "drop_pct",
    "current_price",
    "trades_today",
    "last_trade_was_loss",
    "event_drop",
    "event_spike",
    "event_calm",
    # User rules & violations known at decision time
    "stop_loss_pct",
    "max_trades_per_day",
    "max_position_pct",
    "no_averaging_down",
    "rule_violates_max_trades",
    "rule_violates_position_size",
    "rule_violates_averaging_down",
    # Plain-code consistency flags
    *CONSISTENCY_FLAG_NAMES,
    # History features over last 10 decisions
    "history_total_decisions",
    "history_mistake_count",
    "history_mistake_rate",
    "history_panic_count",
    "history_panic_rate",
    "history_averaging_count",
    "history_averaging_rate",
    "history_fomo_count",
    "history_fomo_rate",
    "history_revenge_count",
    "history_revenge_rate",
    "history_disciplined_count",
    "history_disciplined_rate",
    "history_avg_decision_seconds",
    "history_last_was_mistake",
    "history_consecutive_mistakes",
]

# Canonical label classes
LABEL_CLASSES: List[str] = [
    "disciplined",
    "panic_sell",
    "averaging_down",
    "fomo_buy",
    "revenge_trade",
]


def compute_history_features(prior_decisions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, float]:
    """Computes mistake counts, rates, and patterns over the actor's last 10 decisions.

    Shared between bot simulation, offline model training, and live user inference.
    Handles empty history gracefully by returning 0 for all features.
    """
    if not prior_decisions:
        return {
            "history_total_decisions": 0.0,
            "history_mistake_count": 0.0,
            "history_mistake_rate": 0.0,
            "history_panic_count": 0.0,
            "history_panic_rate": 0.0,
            "history_averaging_count": 0.0,
            "history_averaging_rate": 0.0,
            "history_fomo_count": 0.0,
            "history_fomo_rate": 0.0,
            "history_revenge_count": 0.0,
            "history_revenge_rate": 0.0,
            "history_disciplined_count": 0.0,
            "history_disciplined_rate": 0.0,
            "history_avg_decision_seconds": 0.0,
            "history_last_was_mistake": 0.0,
            "history_consecutive_mistakes": 0.0,
        }

    window = prior_decisions[-10:]
    total = float(len(window))

    panic_count = sum(1.0 for d in window if d.get("label") == "panic_sell" or d.get("true_label") == "panic_sell")
    averaging_count = sum(1.0 for d in window if d.get("label") == "averaging_down" or d.get("true_label") == "averaging_down")
    fomo_count = sum(1.0 for d in window if d.get("label") == "fomo_buy" or d.get("true_label") == "fomo_buy")
    revenge_count = sum(1.0 for d in window if d.get("label") == "revenge_trade" or d.get("true_label") == "revenge_trade")
    disciplined_count = sum(1.0 for d in window if d.get("label") == "disciplined" or d.get("true_label") == "disciplined")

    mistake_count = panic_count + averaging_count + fomo_count + revenge_count
    mistake_rate = mistake_count / total if total > 0 else 0.0

    avg_seconds = sum(float(d.get("decision_seconds", 0.0)) for d in window) / total if total > 0 else 0.0

    last_item = window[-1]
    last_label = last_item.get("label") or last_item.get("true_label") or "disciplined"
    last_was_mistake = 1.0 if last_label != "disciplined" else 0.0

    consecutive_mistakes = 0.0
    for d in reversed(window):
        lbl = d.get("label") or d.get("true_label") or "disciplined"
        if lbl != "disciplined":
            consecutive_mistakes += 1.0
        else:
            break

    return {
        "history_total_decisions": total,
        "history_mistake_count": float(mistake_count),
        "history_mistake_rate": round(float(mistake_rate), 4),
        "history_panic_count": float(panic_count),
        "history_panic_rate": round(float(panic_count / total), 4),
        "history_averaging_count": float(averaging_count),
        "history_averaging_rate": round(float(averaging_count / total), 4),
        "history_fomo_count": float(fomo_count),
        "history_fomo_rate": round(float(fomo_count / total), 4),
        "history_revenge_count": float(revenge_count),
        "history_revenge_rate": round(float(revenge_count / total), 4),
        "history_disciplined_count": float(disciplined_count),
        "history_disciplined_rate": round(float(disciplined_count / total), 4),
        "history_avg_decision_seconds": round(float(avg_seconds), 2),
        "history_last_was_mistake": float(last_was_mistake),
        "history_consecutive_mistakes": float(consecutive_mistakes),
    }


def extract_feature_vector(
    action: str,
    size: float,
    reason: str = "",
    decision_seconds: float = 0.0,
    chart_viewed: bool = True,
    scenario_drop_pct: float = 0.0,
    scenario_current_price: float = 0.0,
    scenario_trades_today: int = 1,
    scenario_last_trade_was_loss: bool = False,
    scenario_event_type: str = "calm",
    stop_loss_pct: float = 2.0,
    max_trades_per_day: int = 5,
    max_position_pct: float = 20.0,
    no_averaging_down: bool = True,
    practice_capital: float = 100000.0,
    history_features: Optional[Dict[str, float]] = None,
    reason_code: Optional[str] = None,
    reason_kind: Optional[str] = None,
    scenario_entry_price: Optional[float] = None,
) -> Dict[str, float]:
    """Builds a standardized feature vector dictionary guaranteed to match FEATURE_COLUMNS."""
    cap = practice_capital if practice_capital and practice_capital > 0 else 100000.0
    size_pct = (size / cap) * 100.0

    act = action.strip().lower()
    evt = scenario_event_type.strip().lower()

    # Resolve canonical reason_code and reason_kind
    resolved_code = (reason_code or "").strip().upper()
    rdef = get_reason(resolved_code) if resolved_code else None
    if rdef is None:
        rdef = map_legacy_reason(reason, act)
        resolved_code = rdef.code
    resolved_kind = (reason_kind or rdef.kind or "unsure").strip().lower()

    # Rule checks at decision time
    violates_max_trades = 1.0 if scenario_trades_today > max_trades_per_day else 0.0
    violates_position_size = 1.0 if size_pct > max_position_pct else 0.0
    entry_p = float(scenario_entry_price or 0.0)
    curr_p = float(scenario_current_price or 0.0)
    drop_p = float(scenario_drop_pct or 0.0)
    is_loss_pos = (entry_p > 0 and curr_p > 0 and curr_p < entry_p) or (drop_p > 0.5)
    violates_averaging_down = 1.0 if (no_averaging_down and act == "buy" and (is_loss_pos or scenario_last_trade_was_loss)) else 0.0

    # Consistency flags computed via the shared plain-code checker
    consistency_flags, _ = compute_consistency_checks(
        action=act,
        size=size,
        reason_code=resolved_code,
        reason_kind=resolved_kind,
        entry_price=entry_p,
        current_price=curr_p,
        drop_pct=drop_p,
        user_trades_today=scenario_trades_today,
        stop_loss_pct=stop_loss_pct,
        max_trades_per_day=max_trades_per_day,
        max_position_pct=max_position_pct,
        no_averaging_down=no_averaging_down,
        practice_capital=cap,
    )

    hf = history_features or compute_history_features([])

    vec: Dict[str, float] = {
        "decision_seconds": round(float(decision_seconds), 2),
        "size": round(float(size), 2),
        "size_pct_of_capital": round(float(size_pct), 2),
        "chart_viewed": 1.0 if chart_viewed else 0.0,
        "action_buy": 1.0 if act == "buy" else 0.0,
        "action_sell": 1.0 if act == "sell" else 0.0,
        "action_hold": 1.0 if act == "hold" else 0.0,
    }

    # Reason code one-hot
    for code in REASON_CODES:
        vec[f"reason_code_{code}"] = 1.0 if resolved_code == code else 0.0

    # Reason kind one-hot
    for kind in VALID_KINDS:
        vec[f"reason_kind_{kind}"] = 1.0 if resolved_kind == kind else 0.0

    # Market context & user rules
    vec.update({
        "drop_pct": round(float(scenario_drop_pct), 2),
        "current_price": round(float(scenario_current_price), 2),
        "trades_today": float(scenario_trades_today),
        "last_trade_was_loss": 1.0 if scenario_last_trade_was_loss else 0.0,
        "event_drop": 1.0 if evt == "drop" else 0.0,
        "event_spike": 1.0 if evt == "spike" else 0.0,
        "event_calm": 1.0 if evt == "calm" else 0.0,
        "stop_loss_pct": round(float(stop_loss_pct), 2),
        "max_trades_per_day": float(max_trades_per_day),
        "max_position_pct": round(float(max_position_pct), 2),
        "no_averaging_down": 1.0 if no_averaging_down else 0.0,
        "rule_violates_max_trades": violates_max_trades,
        "rule_violates_position_size": violates_position_size,
        "rule_violates_averaging_down": violates_averaging_down,
    })

    # Consistency flags
    for flag_name in CONSISTENCY_FLAG_NAMES:
        vec[flag_name] = 1.0 if consistency_flags.get(flag_name, False) else 0.0

    # History features
    vec.update({
        "history_total_decisions": hf["history_total_decisions"],
        "history_mistake_count": hf["history_mistake_count"],
        "history_mistake_rate": hf["history_mistake_rate"],
        "history_panic_count": hf["history_panic_count"],
        "history_panic_rate": hf["history_panic_rate"],
        "history_averaging_count": hf["history_averaging_count"],
        "history_averaging_rate": hf["history_averaging_rate"],
        "history_fomo_count": hf["history_fomo_count"],
        "history_fomo_rate": hf["history_fomo_rate"],
        "history_revenge_count": hf["history_revenge_count"],
        "history_revenge_rate": hf["history_revenge_rate"],
        "history_disciplined_count": hf["history_disciplined_count"],
        "history_disciplined_rate": hf["history_disciplined_rate"],
        "history_avg_decision_seconds": hf["history_avg_decision_seconds"],
        "history_last_was_mistake": hf["history_last_was_mistake"],
        "history_consecutive_mistakes": hf["history_consecutive_mistakes"],
    })

    return vec
