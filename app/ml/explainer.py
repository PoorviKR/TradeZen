"""Plain-sentence explanation generator driven by SHAP top reasons.

- Uses predefined sentence templates with 2 wording variants per feature.
- Strictly uses the user's own numbers from the decision row.
- Appends one fixed 'try this instead' line per mistake type.
- Never calls an LLM, never shows raw SHAP numbers.
- Guarantees that any numbers in the output text are present in the input row.
"""

from typing import Any, Dict, List, Optional

# Two wording variants per feature using numbers strictly present in row
FEATURE_TEMPLATES: Dict[str, List[str]] = {
    "decision_seconds": [
        "You executed this decision in {val} seconds.",
        "Your order was placed after {val} seconds.",
    ],
    "trades_today": [
        "This is trade number {int_val} today against your daily rule of {int_max_trades}.",
        "You took {int_val} trades today while your daily rule specifies {int_max_trades}.",
    ],
    "drop_pct": [
        "The market declined by {val}% right before your entry.",
        "A sudden price drop of {val}% preceded this decision.",
    ],
    "size_pct_of_capital": [
        "Your position size represents {val}% of capital against your rule limit of {max_pos}%.",
        "You allocated {val}% of your capital to this trade against a maximum rule of {max_pos}%.",
    ],
    "size": [
        "You placed an order size of {val}.",
        "Your committed trade capital was {val}.",
    ],
    "chart_viewed": [
        "The scenario chart was reviewed before entering.",
        "You inspected the chart setup prior to making this trade.",
    ],
    "action_buy": [
        "You chose to buy into this market condition.",
        "Your order action was a buy entry.",
    ],
    "action_sell": [
        "You decided to sell your position.",
        "Your executed order was a sell exit.",
    ],
    "action_hold": [
        "You chose to hold and keep your current exposure.",
        "Your decision was to stay on the sidelines and hold.",
    ],
    "reason_fear": [
        "You selected fear as your primary decision trigger.",
        "Your stated motivation was fear of further decline.",
    ],
    "reason_recover": [
        "Your stated reason was wanting to recover a prior loss.",
        "You indicated a desire to recover lost capital as your motivation.",
    ],
    "reason_fomo": [
        "You noted FOMO as your reason for entering.",
        "Your trade was driven by fear of missing out on the move.",
    ],
    "reason_rule": [
        "You cited following your predefined trading plan as your reason.",
        "Your stated rationale was following your established rules.",
    ],
    "reason_social": [
        "You acted on a social tip or external commentary.",
        "External commentary or social sentiment was your primary reason.",
    ],
    "reason_analysis": [
        "Your decision was based on technical chart analysis.",
        "You followed your own technical analysis for this entry.",
    ],
    "current_price": [
        "The market price stood at {val} at decision time.",
        "The asset was trading at {val} when your order was placed.",
    ],
    "last_trade_was_loss": [
        "Your previous trade ended in a loss.",
        "You entered this setup immediately following a losing trade.",
    ],
    "event_drop": [
        "This scenario presented a sharp price drop.",
        "Market conditions featured a steep downward move.",
    ],
    "event_spike": [
        "The price experienced an abrupt upward spike.",
        "This scenario was characterized by a rapid price surge.",
    ],
    "event_calm": [
        "Market price action was calm with low volatility.",
        "The stock was consolidating quietly with minimal price swing.",
    ],
    "stop_loss_pct": [
        "Your stop loss threshold is set at {val}%.",
        "Your risk plan defines a stop loss limit of {val}%.",
    ],
    "max_trades_per_day": [
        "Your daily trading limit is {val} trades.",
        "Your rules specify a cap of {val} trades per session.",
    ],
    "max_position_pct": [
        "Your maximum allowable position size is {val}%.",
        "Your risk rule restricts any single trade to {val}% of capital.",
    ],
    "no_averaging_down": [
        "Your rules strictly prohibit averaging down on losing trades.",
        "You have a rule forbidding buying additional shares into a declining position.",
    ],
    "rule_violates_max_trades": [
        "This trade exceeded your daily trade limit.",
        "You surpassed your permitted number of trades for the day.",
    ],
    "rule_violates_position_size": [
        "Your position exceeded your maximum allowed risk allocation.",
        "The committed size surpassed your maximum single-trade percentage rule.",
    ],
    "rule_violates_averaging_down": [
        "Buying into a losing position breached your averaging down rule.",
        "Adding to this losing position broke your rule against averaging down.",
    ],
    "history_total_decisions": [
        "You have completed {int_val} recorded practice decisions.",
        "This builds upon your past {int_val} practice decisions.",
    ],
    "history_mistake_count": [
        "You recorded {int_val} rule deviations across your recent decisions.",
        "Your recent history includes {int_val} mistake patterns.",
    ],
    "history_mistake_rate": [
        "Your recent mistake rate is {val}.",
        "A mistake rate of {val} was noted in your recent history.",
    ],
    "history_panic_count": [
        "You experienced {int_val} panic sells in recent sessions.",
        "Recent practice logged {int_val} panic exits.",
    ],
    "history_panic_rate": [
        "Panic reactions accounted for a rate of {val} in recent trades.",
        "Your recent panic sell rate was {val}.",
    ],
    "history_averaging_count": [
        "You averaged down {int_val} times in your recent history.",
        "Past decisions show {int_val} instances of adding to losing trades.",
    ],
    "history_averaging_rate": [
        "Your recent averaging down rate stands at {val}.",
        "Averaging down occurred at a rate of {val} across recent trades.",
    ],
    "history_fomo_count": [
        "You made {int_val} FOMO entries in recent practice.",
        "Recent history records {int_val} instances of chasing price rises.",
    ],
    "history_fomo_rate": [
        "Your recent FOMO rate is {val}.",
        "Chasing moves represented a rate of {val} in your recent decisions.",
    ],
    "history_revenge_count": [
        "You logged {int_val} revenge trades following losses.",
        "Recent sessions recorded {int_val} impulsive revenge orders.",
    ],
    "history_revenge_rate": [
        "Your recent revenge trade rate is {val}.",
        "Revenge trades occurred at a rate of {val} in recent sessions.",
    ],
    "history_disciplined_count": [
        "You followed your rules on {int_val} recent decisions.",
        "Disciplined execution was demonstrated on {int_val} recent setups.",
    ],
    "history_disciplined_rate": [
        "Your disciplined execution rate is {val}.",
        "You maintained a disciplined execution rate of {val}.",
    ],
    "history_avg_decision_seconds": [
        "Your typical reaction time across recent decisions was {val} seconds.",
        "Your average decision speed in prior setups was {val} seconds.",
    ],
    "history_last_was_mistake": [
        "Your previous decision was flagged as a rule departure.",
        "You entered this setup following a flawed prior decision.",
    ],
    "history_consecutive_mistakes": [
        "This marks {int_val} consecutive decisions with rule breaches.",
        "You have now recorded {int_val} decisions in a row with rule deviations.",
    ],
}

# Fixed 'try this instead' line per mistake type (contains no numbers to preserve integrity)
TRY_THIS_INSTEAD: Dict[str, str] = {
    "panic_sell": "Try this instead: Define your exit strategy before entering and let your stop-loss order execute automatically rather than cutting in panic.",
    "averaging_down": "Try this instead: Accept the initial loss and protect remaining capital rather than buying more into a losing position.",
    "fomo_buy": "Try this instead: Wait for a confirmed pullback and enter only when your predefined setup criteria are met.",
    "revenge_trade": "Try this instead: Step away from the screen after a losing trade to reset emotionally before placing another order.",
    "disciplined": "Keep this up: Consistent adherence to your rules builds long-term trading discipline.",
}


def explain_text(
    row: Dict[str, Any],
    reasons: List[Dict[str, Any]],
    predicted_label: Optional[str] = None,
) -> str:
    """Renders plain sentences from SHAP top reasons and row values.

    Guarantees:
    - Exactly 2 wording variants available per feature.
    - Numbers in text originate strictly from row.
    - No LLM and no raw SHAP float values shown.
    """
    label = predicted_label or "disciplined"
    friendly_label = label.replace("_", " ")

    lead = f"This looks like a {friendly_label}." if label != "disciplined" else "This looks like a disciplined decision."

    reason_sentences: List[str] = []

    for idx, r in enumerate(reasons[:3]):
        feat_name = r.get("feature", "")
        if feat_name not in FEATURE_TEMPLATES:
            continue

        # If the feature is not in the row, skip to avoid inserting default numbers
        if feat_name not in row:
            continue

        raw_val = row[feat_name]
        val_str = str(raw_val)
        int_val_str = str(int(raw_val)) if isinstance(raw_val, (int, float)) else val_str

        # Pick variant 0 or 1 based on index
        variant_idx = idx % 2
        template = FEATURE_TEMPLATES[feat_name][variant_idx]

        # Check secondary fields
        if "{int_max_trades}" in template:
            if "max_trades_per_day" in row:
                int_max_trades = str(int(row["max_trades_per_day"])) if isinstance(row["max_trades_per_day"], (int, float)) else str(row["max_trades_per_day"])
            else:
                template = "You took {int_val} trades today."
                int_max_trades = ""
        else:
            int_max_trades = ""

        if "{max_pos}" in template:
            if "max_position_pct" in row:
                max_pos = str(row["max_position_pct"])
            else:
                template = "Your position size was {val}% of your capital."
                max_pos = ""
        else:
            max_pos = ""

        sentence = template.format(
            val=val_str,
            int_val=int_val_str,
            int_max_trades=int_max_trades,
            max_pos=max_pos,
        )
        reason_sentences.append(sentence)

    instead_line = TRY_THIS_INSTEAD.get(label, TRY_THIS_INSTEAD["disciplined"])

    # Combine into plain sentences
    parts = [lead] + reason_sentences + [instead_line]
    return " ".join(parts)
