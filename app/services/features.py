"""Shared feature engineering for TradeZen bots, training, and live user inference.

Extracts decision-time features only:
- Excludes bot_name, true_label, IDs, symbols, and future outcome candles.
- Computes history metrics over the actor's last 10 decisions.
- Completely supports empty history.
"""

from typing import Any, Dict, List, Optional

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
    "reason_fear",
    "reason_recover",
    "reason_fomo",
    "reason_rule",
    "reason_social",
    "reason_analysis",
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

    # Slice the last 10 decisions
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
    reason: str,
    decision_seconds: float,
    chart_viewed: bool,
    scenario_drop_pct: float,
    scenario_current_price: float,
    scenario_trades_today: int,
    scenario_last_trade_was_loss: bool,
    scenario_event_type: str,
    stop_loss_pct: float,
    max_trades_per_day: int,
    max_position_pct: float,
    no_averaging_down: bool,
    practice_capital: float,
    history_features: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Builds a standardized feature vector dictionary guaranteed to match FEATURE_COLUMNS."""
    cap = practice_capital if practice_capital and practice_capital > 0 else 100000.0
    size_pct = (size / cap) * 100.0

    act = action.strip().lower()
    rsn = reason.strip().lower()
    evt = scenario_event_type.strip().lower()

    # Rule checks at decision time
    violates_max_trades = 1.0 if scenario_trades_today > max_trades_per_day else 0.0
    violates_position_size = 1.0 if size_pct > max_position_pct else 0.0
    violates_averaging_down = 1.0 if (no_averaging_down and scenario_last_trade_was_loss and act == "buy") else 0.0

    # Ensure history features are populated
    hf = history_features or compute_history_features([])

    vec: Dict[str, float] = {
        # Decision inputs
        "decision_seconds": round(float(decision_seconds), 2),
        "size": round(float(size), 2),
        "size_pct_of_capital": round(float(size_pct), 2),
        "chart_viewed": 1.0 if chart_viewed else 0.0,
        "action_buy": 1.0 if act == "buy" else 0.0,
        "action_sell": 1.0 if act == "sell" else 0.0,
        "action_hold": 1.0 if act == "hold" else 0.0,
        "reason_fear": 1.0 if "fear" in rsn or "panic" in rsn else 0.0,
        "reason_recover": 1.0 if "recover" in rsn or "loss" in rsn or "revenge" in rsn else 0.0,
        "reason_fomo": 1.0 if "fomo" in rsn or "chasing" in rsn else 0.0,
        "reason_rule": 1.0 if "rule" in rsn or "plan" in rsn or "disciplined" in rsn else 0.0,
        "reason_social": 1.0 if "social" in rsn or "tip" in rsn else 0.0,
        "reason_analysis": 1.0 if "analysis" in rsn or "technical" in rsn else 0.0,
        # Market context
        "drop_pct": round(float(scenario_drop_pct), 2),
        "current_price": round(float(scenario_current_price), 2),
        "trades_today": float(scenario_trades_today),
        "last_trade_was_loss": 1.0 if scenario_last_trade_was_loss else 0.0,
        "event_drop": 1.0 if evt == "drop" else 0.0,
        "event_spike": 1.0 if evt == "spike" else 0.0,
        "event_calm": 1.0 if evt == "calm" else 0.0,
        # Rules
        "stop_loss_pct": round(float(stop_loss_pct), 2),
        "max_trades_per_day": float(max_trades_per_day),
        "max_position_pct": round(float(max_position_pct), 2),
        "no_averaging_down": 1.0 if no_averaging_down else 0.0,
        "rule_violates_max_trades": violates_max_trades,
        "rule_violates_position_size": violates_position_size,
        "rule_violates_averaging_down": violates_averaging_down,
        # History features
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
    }

    return vec
