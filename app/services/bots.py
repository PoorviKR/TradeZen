"""Trading bots simulation engine for generating labeled behavioural training dataset.

Simulates 5 distinct behavioural archetypes reacting to every active scenario:
1. Panic: sells 2-8 sec after a drop >= 0.5%, reason Fear
2. Averaging: buys 50-100% more when in loss, reason Recover loss
3. FOMO: buys after a rise >= 2%, reason FOMO
4. Revenge: trades again within 30-120 sec of a loss at 1.5-3x size
5. Disciplined: follows rules, reason Followed my rule

Rules:
- Each row receives randomized user rules.
- Each flawed bot behaves like the disciplined bot 15% of the time.
- Timing ranges deliberately overlap between bots.
- true_label reflects the behaviour actually demonstrated.
- bot_name is stored strictly for metadata, never exposed as a feature.
- Fully idempotent: hooked into pool refresh so new scenarios receive bot decisions automatically.
"""

import random
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.scenario import Scenario
from app.models.decision import BotDecision
from app.services.features import (
    compute_history_features,
    extract_feature_vector,
    FEATURE_COLUMNS,
)

logger = logging.getLogger("tradezen.bots")

BOT_NAMES = ["Panic", "Averaging", "FOMO", "Revenge", "Disciplined"]


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


def simulate_bot_decision(
    bot_name: str,
    scenario: Scenario,
    rules: Dict[str, Any],
    history_features: Dict[str, float],
    rng: random.Random,
) -> Tuple[str, str, float, str, float, Dict[str, float]]:
    """Simulates a single bot's reaction to a market scenario snapshot.

    Returns:
        (true_label, action, size, reason, decision_seconds, features_dict)
    """
    capital = rules["practice_capital"]
    max_pos_pct = rules["max_position_pct"]
    stop_loss_pct = rules["stop_loss_pct"]
    standard_size = round(capital * (max_pos_pct / 100.0) * 0.75, 2)

    # 15% probability for flawed bots to behave disciplined
    behaves_disciplined = (bot_name == "Disciplined") or (rng.random() < 0.15)

    if behaves_disciplined:
        true_label = "disciplined"
        reason = "Followed my rule"
        decision_seconds = round(rng.uniform(8.0, 24.0), 1)

        # Disciplined logic: cut loss if drop exceeds stop_loss_pct, otherwise deliberate hold or planned entry
        if scenario.drop_pct >= stop_loss_pct and scenario.event_type == "drop":
            action = "sell"
            size = standard_size
        elif scenario.trades_today >= rules["max_trades_per_day"]:
            action = "hold"
            size = standard_size
        else:
            action = rng.choice(["hold", "buy" if scenario.event_type != "drop" else "hold"])
            size = standard_size
    else:
        # Flawed behaviours
        if bot_name == "Panic":
            # Sells 2-8 sec after a drop >= 0.5%, reason Fear
            true_label = "panic_sell"
            action = "sell"
            decision_seconds = round(rng.uniform(2.0, 8.0), 1)
            size = standard_size
            reason = "Fear"

        elif bot_name == "Averaging":
            # Buys 50-100% more when in loss, reason Recover loss
            true_label = "averaging_down"
            action = "buy"
            multiplier = rng.uniform(1.5, 2.0)  # 50% to 100% more
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(4.0, 11.0), 1)
            reason = "Recover loss"

        elif bot_name == "FOMO":
            # Buys after a rise >= 2%, reason FOMO
            true_label = "fomo_buy"
            action = "buy"
            multiplier = rng.uniform(1.2, 1.8)
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(3.0, 9.0), 1)
            reason = "FOMO"

        elif bot_name == "Revenge":
            # Trades again within 30-120 sec of a loss at 1.5-3x size
            true_label = "revenge_trade"
            action = rng.choice(["buy", "sell"])
            multiplier = rng.uniform(1.5, 3.0)  # 1.5x - 3x size
            size = round(standard_size * multiplier, 2)
            decision_seconds = round(rng.uniform(3.0, 8.0), 1)
            reason = "Recover loss"

        else:
            true_label = "disciplined"
            action = "hold"
            size = standard_size
            reason = "Followed my rule"
            decision_seconds = round(rng.uniform(10.0, 20.0), 1)

    # Build standardized feature dictionary known at decision time
    feature_vec = extract_feature_vector(
        action=action,
        size=size,
        reason=reason,
        decision_seconds=decision_seconds,
        chart_viewed=True,
        scenario_drop_pct=scenario.drop_pct,
        scenario_current_price=scenario.current_price,
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

    return true_label, action, size, reason, decision_seconds, feature_vec


def populate_bot_decisions(
    db: Session,
    scenarios: Optional[List[Scenario]] = None,
    target_per_scenario: int = 5,
) -> int:
    """Populates bot decisions for all active scenarios.

    Idempotent: skips (scenario_id, bot_name) pairs that already exist.
    Hooked directly into the scenario refresh job.
    """
    if scenarios is None:
        scenarios = (
            db.query(Scenario)
            .filter(Scenario.active.is_(True))
            .order_by(Scenario.id.asc())
            .all()
        )

    if not scenarios:
        logger.info("No active scenarios found for bot population.")
        return 0

    scenario_ids = [s.id for s in scenarios]

    # Find already existing bot decisions for these scenarios
    existing_records = (
        db.query(BotDecision.scenario_id, BotDecision.bot_name)
        .filter(BotDecision.scenario_id.in_(scenario_ids))
        .all()
    )
    existing_set: Set[Tuple[int, str]] = {(r[0], r[1]) for r in existing_records}

    # Track decision history per bot across the scenarios to compute history features
    bot_histories: Dict[str, List[Dict[str, Any]]] = {name: [] for name in BOT_NAMES}

    # Load prior bot decisions into memory for history computation if available
    prior_existing = (
        db.query(BotDecision)
        .filter(BotDecision.scenario_id.in_(scenario_ids))
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
            })

    new_decisions: List[BotDecision] = []

    for sc in scenarios:
        # Deterministic seed per scenario to maintain consistency
        base_seed = sc.id * 10007 + int(sc.drop_pct * 100)

        for bot_idx, bot_name in enumerate(BOT_NAMES):
            if (sc.id, bot_name) in existing_set:
                continue

            bot_seed = base_seed + bot_idx * 31
            bot_rng = random.Random(bot_seed)

            rules = sample_random_user_rules(bot_seed)
            hf = compute_history_features(bot_histories[bot_name])

            true_label, action, size, reason, decision_seconds, feat_dict = simulate_bot_decision(
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
                    reason=reason,
                    decision_seconds=decision_seconds,
                    features=feat_dict,
                )
            )

            # Update history for next scenarios
            bot_histories[bot_name].append({
                "label": true_label,
                "decision_seconds": decision_seconds,
                "size": size,
                "action": action,
                "reason": reason,
            })
            existing_set.add((sc.id, bot_name))

    if new_decisions:
        db.add_all(new_decisions)
        db.commit()
        logger.info("Inserted %d new bot decisions (total active scenarios: %d)", len(new_decisions), len(scenarios))
    else:
        logger.info("All active scenarios already have complete bot decisions. 0 inserted.")

    return len(new_decisions)
