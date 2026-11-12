"""Trading bots simulation engine for generating labeled behavioural training dataset.

Simulates 5 distinct behavioural archetypes reacting to every scenario:
1. Panic: sells 2-8 sec after a drop, overlapping SELL reasons + 15% noise
2. Averaging: buys 50-100% more when in loss, overlapping BUY reasons + 15% noise
3. FOMO: buys after a rise, overlapping BUY reasons + 15% noise
4. Revenge: trades impulsively after a loss at 1.5-3x size, overlapping BUY/SELL/HOLD reasons + 15% noise
5. Disciplined: follows rules, overlapping action-consistent reasons + 15% noise

Rules:
- Each row receives randomized user rules.
- Each flawed bot behaves like the disciplined bot 15% of the time.
- Reason selection uses overlapping distributions + 15% noise across the chosen action's
  catalogue so no reason maps 100% to a single label.
- true_label reflects the behaviour actually demonstrated.
- bot_name is stored strictly for metadata, never exposed as a feature.
- Fully idempotent and versioned by catalogue_version: regenerating keeps old rows
  under previous catalogue_version values.
"""

import random
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from app.core.reasons import (
    CATALOGUE_VERSION,
    REASON_BY_CODE,
    REASONS_BY_ACTION,
)
from app.models.scenario import Scenario
from app.models.decision import BotDecision
from app.services.features import (
    compute_history_features,
    extract_feature_vector,
)

logger = logging.getLogger("tradezen.bots")

BOT_NAMES = ["Panic", "Averaging", "FOMO", "Revenge", "Disciplined"]

REASON_NOISE_PROB = 0.15


def sample_random_user_rules(seed_val: int) -> Dict[str, Any]:
    """Generates randomized user rules for a scenario decision row."""
    rng = random.Random(seed_val)
    return {
        "stop_loss_pct": round(rng.choice([1.5, 2.0, 2.5, 3.0, 3.5]), 1),
        "max_trades_per_day": rng.choice([3, 4, 5, 6, 7]),
        "no_averaging_down": True,
        "max_position_pct": round(rng.choice([10.0, 15.0, 20.0, 25.0]), 1),
        "practice_capital": float(rng.choice([50000, 100000, 150000, 200000])),
    }


def _pick_weighted_reason(
    action: str,
    weighted_codes: List[Tuple[str, float]],
    rng: random.Random,
    exclude_codes: Optional[Set[str]] = None,
) -> str:
    """Samples a reason_code from overlapping weighted distribution with 15% noise."""
    valid_for_action = [
        r.code
        for r in REASONS_BY_ACTION[action]
        if not exclude_codes or r.code not in exclude_codes
    ]
    if not valid_for_action:
        valid_for_action = [r.code for r in REASONS_BY_ACTION[action]]

    if rng.random() < REASON_NOISE_PROB:
        return rng.choice(valid_for_action)

    codes = [c for c, _ in weighted_codes]
    weights = [w for _, w in weighted_codes]
    return rng.choices(codes, weights=weights, k=1)[0]


def simulate_bot_decision(
    bot_name: str,
    scenario: Scenario,
    rules: Dict[str, Any],
    history_features: Dict[str, float],
    rng: random.Random,
) -> Tuple[str, str, float, str, str, str, float, Dict[str, float]]:
    """Simulates a single bot's reaction to a market scenario snapshot.

    Returns:
        (true_label, action, size, reason_label, reason_code, reason_kind, decision_seconds, features_dict)
    """
    capital = rules["practice_capital"]
    max_pos_pct = rules["max_position_pct"]
    stop_loss_pct = rules["stop_loss_pct"]
    standard_size = round(capital * (max_pos_pct / 100.0) * 0.75, 2)

    entry_p = float(getattr(scenario, "entry_price", 0.0) or 0.0)
    curr_p = float(getattr(scenario, "current_price", 0.0) or 0.0)
    drop_p = float(getattr(scenario, "drop_pct", 0.0) or 0.0)
    overall_drop = ((entry_p - curr_p) / entry_p) * 100.0 if (entry_p > 0 and curr_p > 0) else drop_p
    effective_loss = max(drop_p, overall_drop) if drop_p > 0 else overall_drop
    stop_hit = effective_loss >= stop_loss_pct

    # 15% probability for flawed bots to behave disciplined
    behaves_disciplined = (bot_name == "Disciplined") or (rng.random() < 0.15)

    if behaves_disciplined:
        true_label = "disciplined"
        decision_seconds = round(rng.uniform(8.0, 24.0), 1)
        size = standard_size

        if stop_hit and scenario.event_type == "drop":
            action = "sell"
            reason_code = _pick_weighted_reason(
                action="sell",
                weighted_codes=[
                    ("SELL_STOP_HIT", 0.70),
                    ("SELL_TARGET", 0.20),
                    ("SELL_PROTECT_CAPITAL", 0.10),
                ],
                rng=rng,
            )
        elif scenario.trades_today >= rules["max_trades_per_day"]:
            action = "hold"
            reason_code = _pick_weighted_reason(
                action="hold",
                weighted_codes=[
                    ("HOLD_PLAN_INTACT", 0.65),
                    ("HOLD_LET_PROFIT_RUN", 0.20),
                    ("HOLD_WAIT_CONFIRM", 0.15),
                ],
                rng=rng,
            )
        elif scenario.event_type == "spike" and rng.random() < 0.30:
            action = "sell"
            reason_code = _pick_weighted_reason(
                action="sell",
                weighted_codes=[
                    ("SELL_TARGET", 0.65),
                    ("SELL_PROTECT_CAPITAL", 0.35),
                ],
                rng=rng,
                exclude_codes={"SELL_STOP_HIT"},
            )
        else:
            action = rng.choice(["hold", "buy" if scenario.event_type != "drop" else "hold"])
            if action == "buy":
                reason_code = _pick_weighted_reason(
                    action="buy",
                    weighted_codes=[
                        ("BUY_PLANNED", 0.65),
                        ("BUY_ADD_WINNER", 0.20),
                        ("BUY_DIP_CHEAP", 0.15),
                    ],
                    rng=rng,
                )
            else:
                reason_code = _pick_weighted_reason(
                    action="hold",
                    weighted_codes=[
                        ("HOLD_PLAN_INTACT", 0.65),
                        ("HOLD_LET_PROFIT_RUN", 0.20),
                        ("HOLD_WAIT_CONFIRM", 0.15),
                    ],
                    rng=rng,
                )
    else:
        if bot_name == "Panic":
            true_label = "panic_sell"
            action = "sell"
            decision_seconds = round(rng.uniform(2.0, 8.0), 1)
            size = standard_size
            reason_code = _pick_weighted_reason(
                action="sell",
                weighted_codes=[
                    ("SELL_PANIC", 0.55),
                    ("SELL_FRUSTRATED", 0.15),
                    ("SELL_PROTECT_CAPITAL", 0.15),
                    ("SELL_STOP_HIT", 0.15),
                ],
                rng=rng,
            )

        elif bot_name == "Averaging":
            true_label = "averaging_down"
            action = "buy"
            multiplier = rng.uniform(1.5, 2.0)
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(4.0, 11.0), 1)
            reason_code = _pick_weighted_reason(
                action="buy",
                weighted_codes=[
                    ("BUY_RECOVER_LOSS", 0.40),
                    ("BUY_BALANCE_LOSS", 0.30),
                    ("BUY_DIP_CHEAP", 0.15),
                    ("BUY_PLANNED", 0.10),
                    ("BUY_UNSURE", 0.05),
                ],
                rng=rng,
            )

        elif bot_name == "FOMO":
            true_label = "fomo_buy"
            action = "buy"
            multiplier = rng.uniform(1.2, 1.8)
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(3.0, 9.0), 1)
            reason_code = _pick_weighted_reason(
                action="buy",
                weighted_codes=[
                    ("BUY_FOMO", 0.55),
                    ("BUY_TIP", 0.15),
                    ("BUY_ADD_WINNER", 0.15),
                    ("BUY_PLANNED", 0.10),
                    ("BUY_UNSURE", 0.05),
                ],
                rng=rng,
            )

        elif bot_name == "Revenge":
            true_label = "revenge_trade"
            action = rng.choices(["buy", "sell", "hold"], weights=[0.45, 0.45, 0.10], k=1)[0]
            multiplier = rng.uniform(1.5, 3.0)
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(3.0, 8.0), 1)
            if action == "buy":
                reason_code = _pick_weighted_reason(
                    action="buy",
                    weighted_codes=[
                        ("BUY_RECOVER_LOSS", 0.45),
                        ("BUY_BALANCE_LOSS", 0.20),
                        ("BUY_FOMO", 0.15),
                        ("BUY_TIP", 0.10),
                        ("BUY_UNSURE", 0.10),
                    ],
                    rng=rng,
                )
            elif action == "sell":
                reason_code = _pick_weighted_reason(
                    action="sell",
                    weighted_codes=[
                        ("SELL_FRUSTRATED", 0.45),
                        ("SELL_PANIC", 0.20),
                        ("SELL_EARLY_PROFIT", 0.15),
                        ("SELL_TIP", 0.10),
                        ("SELL_UNSURE", 0.10),
                    ],
                    rng=rng,
                )
            else:
                reason_code = _pick_weighted_reason(
                    action="hold",
                    weighted_codes=[
                        ("HOLD_WAIT_BREAKEVEN", 0.40),
                        ("HOLD_AVOID_LOSS", 0.30),
                        ("HOLD_FROZEN", 0.20),
                        ("HOLD_UNSURE", 0.10),
                    ],
                    rng=rng,
                )

        else:
            true_label = "disciplined"
            action = "hold"
            size = standard_size
            decision_seconds = round(rng.uniform(10.0, 20.0), 1)
            reason_code = "HOLD_PLAN_INTACT"

    rdef = REASON_BY_CODE[reason_code]
    reason_label = rdef.label
    reason_kind = rdef.kind

    feature_vec = extract_feature_vector(
        action=action,
        size=size,
        reason=reason_label,
        reason_code=reason_code,
        reason_kind=reason_kind,
        decision_seconds=decision_seconds,
        chart_viewed=True,
        scenario_drop_pct=scenario.drop_pct,
        scenario_current_price=scenario.current_price,
        scenario_entry_price=scenario.entry_price,
        scenario_trades_today=scenario.trades_today,
        scenario_last_trade_was_loss=scenario.last_trade_was_loss,
        scenario_event_type=scenario.event_type,
        stop_loss_pct=rules["stop_loss_pct"],
        max_trades_per_day=rules["max_trades_per_day"],
        max_position_pct=rules["max_position_pct"],
        no_averaging_down=rules["no_averaging_down"],
        practice_capital=rules["practice_capital"],
        history_features=history_features,
    )

    return true_label, action, size, reason_label, reason_code, reason_kind, decision_seconds, feature_vec


def populate_bot_decisions(
    db: Session,
    scenarios: Optional[List[Scenario]] = None,
    target_per_scenario: int = 5,
    catalogue_version: str = CATALOGUE_VERSION,
    include_inactive: bool = False,
) -> int:
    """Populates versioned bot decisions for scenarios.

    Idempotent per (scenario_id, bot_name, catalogue_version):
    - Keeps existing rows under older catalogue_version values untouched.
    - Inserts missing rows for `catalogue_version`.
    """
    if scenarios is None:
        query = db.query(Scenario)
        if not include_inactive:
            query = query.filter(Scenario.active.is_(True))
        scenarios = query.order_by(Scenario.id.asc()).all()

    if not scenarios:
        logger.info("No scenarios found for bot population.")
        return 0

    scenario_ids = [s.id for s in scenarios]

    existing_records = (
        db.query(BotDecision.scenario_id, BotDecision.bot_name)
        .filter(
            BotDecision.scenario_id.in_(scenario_ids),
            BotDecision.catalogue_version == catalogue_version,
        )
        .all()
    )
    existing_set: Set[Tuple[int, str]] = {(r[0], r[1]) for r in existing_records}

    bot_histories: Dict[str, List[Dict[str, Any]]] = {name: [] for name in BOT_NAMES}

    prior_existing = (
        db.query(BotDecision)
        .filter(
            BotDecision.scenario_id.in_(scenario_ids),
            BotDecision.catalogue_version == catalogue_version,
        )
        .order_by(BotDecision.id.asc())
        .all()
    )
    for bd in prior_existing:
        if bd.bot_name in bot_histories:
            bot_histories[bd.bot_name].append({
                "label": bd.true_label,
                "decision_seconds": bd.decision_seconds,
                "size": bd.size,
                "action": bd.action,
                "reason": bd.reason,
                "reason_code": bd.reason_code,
            })

    new_decisions: List[BotDecision] = []

    for sc in scenarios:
        base_seed = sc.id * 10007 + int(abs(sc.drop_pct) * 100)

        for bot_idx, bot_name in enumerate(BOT_NAMES):
            if (sc.id, bot_name) in existing_set:
                continue

            bot_seed = base_seed + bot_idx * 31
            bot_rng = random.Random(bot_seed)

            rules = sample_random_user_rules(bot_seed)
            hf = compute_history_features(bot_histories[bot_name])

            (
                true_label,
                action,
                size,
                reason_label,
                reason_code,
                reason_kind,
                decision_seconds,
                feat_dict,
            ) = simulate_bot_decision(
                bot_name=bot_name,
                scenario=sc,
                rules=rules,
                history_features=hf,
                rng=bot_rng,
            )

            new_decisions.append(
                BotDecision(
                    scenario_id=sc.id,
                    actor_type="bot",
                    bot_name=bot_name,
                    true_label=true_label,
                    action=action,
                    size=size,
                    reason=reason_label,
                    reason_code=reason_code,
                    reason_kind=reason_kind,
                    catalogue_version=catalogue_version,
                    migrated=False,
                    decision_seconds=decision_seconds,
                    features=feat_dict,
                )
            )

            bot_histories[bot_name].append({
                "label": true_label,
                "decision_seconds": decision_seconds,
                "size": size,
                "action": action,
                "reason": reason_label,
                "reason_code": reason_code,
            })
            existing_set.add((sc.id, bot_name))

    if new_decisions:
        db.add_all(new_decisions)
        db.commit()
        logger.info(
            "Inserted %d new bot decisions under catalogue_version=%s (scenarios: %d)",
            len(new_decisions),
            catalogue_version,
            len(scenarios),
        )
    else:
        logger.info(
            "All scenarios already have bot decisions for catalogue_version=%s. 0 inserted.",
            catalogue_version,
        )

    return len(new_decisions)


def regenerate_bot_decisions(
    db: Session,
    catalogue_version: str = CATALOGUE_VERSION,
) -> int:
    """Regenerates bot decisions for ALL scenarios (active and inactive) under catalogue_version.

    Idempotent and preserves rows under older catalogue_version values.
    """
    return populate_bot_decisions(
        db=db,
        scenarios=None,
        catalogue_version=catalogue_version,
        include_inactive=True,
    )


def main():
    """CLI runner: python -m app.services.bots"""
    import sys
    from app.db.session import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db = SessionLocal()
    try:
        inserted = regenerate_bot_decisions(db, catalogue_version=CATALOGUE_VERSION)
        print(f"Bot regeneration complete for {CATALOGUE_VERSION}: inserted {inserted} rows.")
    except Exception as exc:
        print(f"Bot regeneration failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
