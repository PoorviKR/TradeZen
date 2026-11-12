"""Plain-sentence explanation generator driven by SHAP top reasons.

- Uses predefined sentence templates with 2 wording variants per feature and per reason code.
- Strictly uses the user's own numbers from the decision row.
- Appends one fixed 'try this instead' line per mistake type.
- Provides a safe fallback sentence for unknown reason codes.
- Never calls an LLM, never shows raw SHAP numbers.
- Guarantees that any numbers in the output text are present in the input row.
"""

from typing import Any, Dict, List, Optional

UNKNOWN_REASON_FALLBACK = "You recorded a decision reason outside the standard catalogue."

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
    # BUY reason codes (2 variants each)
    "reason_code_BUY_PLANNED": [
        "You indicated this buy matched your predefined entry plan.",
        "Your stated reason was executing a planned buy setup.",
    ],
    "reason_code_BUY_ADD_WINNER": [
        "You chose to buy as a way of adding to a winning position.",
        "Your stated rationale was scaling into an existing winner.",
    ],
    "reason_code_BUY_DIP_CHEAP": [
        "You bought because the price dipped and looked cheap.",
        "Your stated reason was buying a dip at an attractive price.",
    ],
    "reason_code_BUY_BALANCE_LOSS": [
        "You bought more shares to average down and balance a loss.",
        "Your stated motivation was lowering your average cost during a loss.",
    ],
    "reason_code_BUY_RECOVER_LOSS": [
        "You bought in an effort to recover a previous loss.",
        "Your stated trigger was trying to win back lost capital.",
    ],
    "reason_code_BUY_FOMO": [
        "You bought out of FOMO while price was running away.",
        "Your entry was driven by fear of missing out on the move.",
    ],
    "reason_code_BUY_TIP": [
        "You placed this buy based on an external tip or social call.",
        "Your stated motivation was following an outside tip or commentary.",
    ],
    "reason_code_BUY_UNSURE": [
        "You entered a buy without a clear reason or out of uncertainty.",
        "Your stated reason for buying was being unsure.",
    ],
    # HOLD reason codes (2 variants each)
    "reason_code_HOLD_PLAN_INTACT": [
        "You held because your trading plan remained intact and your stop was untouched.",
        "Your stated reason for holding was that your plan was still valid.",
    ],
    "reason_code_HOLD_LET_PROFIT_RUN": [
        "You held to let an open winning trade continue running.",
        "Your stated rationale was giving a profitable move room to run.",
    ],
    "reason_code_HOLD_WAIT_CONFIRM": [
        "You held while waiting for clearer confirmation on the chart.",
        "Your stated reason was pausing for confirmation before acting.",
    ],
    "reason_code_HOLD_WAIT_BREAKEVEN": [
        "You held in hopes the trade would return to breakeven.",
        "Your stated motivation was waiting to get back to your entry price.",
    ],
    "reason_code_HOLD_AVOID_LOSS": [
        "You held because you did not want to book an open loss.",
        "Your stated reason was avoiding realizing a loss on the position.",
    ],
    "reason_code_HOLD_FROZEN": [
        "You held because you felt frozen and unsure how to react.",
        "Your decision to hold stemmed from hesitation and feeling stuck.",
    ],
    "reason_code_HOLD_TIP": [
        "You held based on an outside tip advising you not to exit.",
        "Your stated reason for holding was following someone else's advice.",
    ],
    "reason_code_HOLD_UNSURE": [
        "You held while unsure of what action to take.",
        "Your stated reason for holding was uncertainty.",
    ],
    # SELL reason codes (2 variants each)
    "reason_code_SELL_STOP_HIT": [
        "You sold because your predefined stop-loss level was hit.",
        "Your stated exit reason was respecting a triggered stop-loss.",
    ],
    "reason_code_SELL_TARGET": [
        "You sold because your profit target was reached.",
        "Your stated rationale was taking profits at your planned target.",
    ],
    "reason_code_SELL_PROTECT_CAPITAL": [
        "You sold to protect your capital according to your risk rules.",
        "Your stated reason was preserving capital in line with your rule.",
    ],
    "reason_code_SELL_PANIC": [
        "You sold in panic out of fear of a larger drop.",
        "Your exit was driven by fear and panic during the decline.",
    ],
    "reason_code_SELL_EARLY_PROFIT": [
        "You sold early to lock in a small profit out of fear.",
        "Your stated motivation was grabbing an early profit before your target.",
    ],
    "reason_code_SELL_FRUSTRATED": [
        "You exited because you felt frustrated with how the trade moved.",
        "Your stated reason for selling was frustration with the position.",
    ],
    "reason_code_SELL_TIP": [
        "You sold after hearing an external tip or news commentary.",
        "Your exit was prompted by outside commentary rather than your plan.",
    ],
    "reason_code_SELL_UNSURE": [
        "You exited the trade while feeling unsure.",
        "Your stated reason for selling was uncertainty.",
    ],
    # Reason kind features (2 variants each)
    "reason_kind_plan": [
        "Your stated reason falls under plan-based reasoning.",
        "You selected a rule-aligned, plan-based rationale.",
    ],
    "reason_kind_mixed": [
        "Your stated reason reflects mixed discretionary and plan judgment.",
        "You selected a mixed rationale combining chart judgment and discretion.",
    ],
    "reason_kind_emotion": [
        "Your stated reason reflects an emotion-driven impulse.",
        "You selected an emotionally driven rationale for this trade.",
    ],
    "reason_kind_external": [
        "Your stated reason relies on external tips or commentary.",
        "You based this decision on outside input rather than your rules.",
    ],
    "reason_kind_unsure": [
        "Your stated reason indicates uncertainty about the setup.",
        "You noted uncertainty as your reason for this decision.",
    ],
    # Consistency flags (2 variants each)
    "consistency_sell_stop_not_hit": [
        "You cited a stop-loss exit even though the price drop had not reached your stop.",
        "Your stop-loss reason did not match the actual move against your stop threshold.",
    ],
    "consistency_hold_past_stop": [
        "You cited your plan being intact even though the loss was already past your stop.",
        "Holding under a plan-intact reason conflicted with the breach of your stop-loss.",
    ],
    "consistency_add_winner_in_loss": [
        "You cited adding to a winner while the position was actually in a loss.",
        "The add-to-winner reason contradicted the current losing price move.",
    ],
    "consistency_averaging_against_rule": [
        "Your stated averaging or recovery reason directly conflicted with your no-averaging-down rule.",
        "You selected an averaging-down rationale despite your rule prohibiting it.",
    ],
    "consistency_plan_contradicts_numbers": [
        "Your plan-based reason contradicted the scenario numbers or your active rule limits.",
        "There was a mismatch between your stated plan reason and the scenario metrics.",
    ],
    "consistency_has_contradiction": [
        "A mismatch was detected between your chosen reason and the trade numbers.",
        "Your stated reason conflicted with your active rules or scenario conditions.",
    ],
    # Market & rule context
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


def explain_reason_code(reason_code: Optional[str], variant_idx: int = 0) -> str:
    """Renders a plain-sentence explanation for a reason code with safe unknown fallback."""
    if not reason_code:
        return UNKNOWN_REASON_FALLBACK
    feat_key = f"reason_code_{reason_code.strip().upper()}"
    variants = FEATURE_TEMPLATES.get(feat_key)
    if not variants:
        return UNKNOWN_REASON_FALLBACK
    return variants[variant_idx % len(variants)]


def explain_text(
    row: Dict[str, Any],
    reasons: List[Dict[str, Any]],
    predicted_label: Optional[str] = None,
) -> str:
    """Renders plain sentences from SHAP top reasons and row values.

    Guarantees:
    - 2 wording variants available per feature and per new reason code.
    - Safe fallback sentence for unknown reason codes.
    - Numbers in text originate strictly from row.
    - No LLM and no raw SHAP float values shown.
    """
    label = predicted_label or "disciplined"
    friendly_label = label.replace("_", " ")

    lead = f"This looks like a {friendly_label}." if label != "disciplined" else "This looks like a disciplined decision."

    reason_sentences: List[str] = []

    for idx, r in enumerate(reasons[:3]):
        feat_name = r.get("feature", "")
        if feat_name.startswith("reason_code_") and feat_name not in FEATURE_TEMPLATES:
            reason_sentences.append(UNKNOWN_REASON_FALLBACK)
            continue

        if feat_name not in FEATURE_TEMPLATES:
            continue

        if feat_name not in row:
            continue

        raw_val = row[feat_name]
        val_str = str(raw_val)
        int_val_str = str(int(raw_val)) if isinstance(raw_val, (int, float)) else val_str

        variant_idx = idx % 2
        template = FEATURE_TEMPLATES[feat_name][variant_idx]

        if "{int_max_trades}" in template:
            if "max_trades_per_day" in row:
                int_max_trades = (
                    str(int(row["max_trades_per_day"]))
                    if isinstance(row["max_trades_per_day"], (int, float))
                    else str(row["max_trades_per_day"])
                )
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

    parts = [lead] + reason_sentences + [instead_line]
    return " ".join(parts)
