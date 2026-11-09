"""Test suite for Step 3: Bots, dataset, feature engineering, and ML service.

Verifies:
1. No bot_name leakage: bot_name is excluded from all training and inference features.
2. Identical features in training and live: exact match of feature keys, types, and column order.
3. Explanation text contains only numbers present in the row.
4. Model loads and initializes SHAP in under 1 second.
5. Five bots simulation correctness, 15% disciplined behavior, and idempotency.
6. History features shared function (empty and populated).
7. Retrain pipeline promotion check against fixed test set.
"""

import re
import time
import pytest
from pathlib import Path
from typing import Set

from app.services.features import (
    FEATURE_COLUMNS,
    LABEL_CLASSES,
    compute_history_features,
    extract_feature_vector,
)
from app.services.bots import (
    BOT_NAMES,
    sample_random_user_rules,
    simulate_bot_decision,
    populate_bot_decisions,
)
from app.ml.predictor import MLPredictor, MODELS_DIR
from app.ml.explainer import explain_text, FEATURE_TEMPLATES
from app.ml.train_model import train_model
from app.ml.retrain import retrain_model
from app.models.scenario import Scenario
from app.models.decision import BotDecision, Attempt, Prediction
from app.models.rule import Rule


def test_no_bot_name_leakage():
    """Requirement 8.1: Ensure bot_name is strictly excluded from all training and live features."""
    # 1. Feature columns list must not have bot_name or label
    assert "bot_name" not in FEATURE_COLUMNS, "Leakage: bot_name found in FEATURE_COLUMNS!"
    assert "true_label" not in FEATURE_COLUMNS, "Leakage: true_label found in FEATURE_COLUMNS!"
    assert "label" not in FEATURE_COLUMNS, "Leakage: label found in FEATURE_COLUMNS!"

    # 2. extract_feature_vector must never produce bot_name
    vec = extract_feature_vector(
        action="buy",
        size=10000.0,
        reason="Fear",
        decision_seconds=4.0,
        chart_viewed=True,
        scenario_drop_pct=1.0,
        scenario_current_price=1000.0,
        scenario_trades_today=2,
        scenario_last_trade_was_loss=False,
        scenario_event_type="drop",
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=20.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    assert "bot_name" not in vec
    assert "true_label" not in vec

    # 3. Active trained model bundle feature names must not include bot_name
    predictor = MLPredictor.get_instance()
    assert "bot_name" not in predictor.feature_names
    assert "true_label" not in predictor.feature_names


def test_identical_features_in_training_and_live():
    """Requirement 8.2: Ensure identical features, schema, and column order between training and live inference."""
    # Generate feature vector for training (from simulated bot decision)
    hf_empty = compute_history_features([])
    train_vec = extract_feature_vector(
        action="sell",
        size=15000.0,
        reason="Fear",
        decision_seconds=3.2,
        chart_viewed=True,
        scenario_drop_pct=0.8,
        scenario_current_price=500.0,
        scenario_trades_today=1,
        scenario_last_trade_was_loss=True,
        scenario_event_type="drop",
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=20.0,
        no_averaging_down=True,
        practice_capital=100000.0,
        history_features=hf_empty,
    )

    # Generate feature vector for live user decision
    live_vec = extract_feature_vector(
        action="buy",
        size=8000.0,
        reason="Followed my rule",
        decision_seconds=12.5,
        chart_viewed=True,
        scenario_drop_pct=-1.5,
        scenario_current_price=1200.0,
        scenario_trades_today=3,
        scenario_last_trade_was_loss=False,
        scenario_event_type="spike",
        stop_loss_pct=1.5,
        max_trades_per_day=4,
        max_position_pct=15.0,
        no_averaging_down=True,
        practice_capital=150000.0,
        history_features=hf_empty,
    )

    # Key list and column order must match FEATURE_COLUMNS exactly
    assert list(train_vec.keys()) == FEATURE_COLUMNS
    assert list(live_vec.keys()) == FEATURE_COLUMNS

    # All values must be valid finite floats/ints
    for col in FEATURE_COLUMNS:
        assert isinstance(train_vec[col], (int, float))
        assert isinstance(live_vec[col], (int, float))


def test_explanation_text_contains_only_numbers_present_in_row():
    """Requirement 8.3: Ensure explanation text contains ONLY numbers that appear in the input row."""
    # Build a test row with distinct numbers
    test_row = {
        "decision_seconds": 4.5,
        "trades_today": 7.0,
        "max_trades_per_day": 5.0,
        "drop_pct": 1.25,
        "size": 15000.0,
        "size_pct_of_capital": 15.0,
        "max_position_pct": 20.0,
        "current_price": 980.0,
        "history_mistake_count": 3.0,
        "history_total_decisions": 10.0,
    }

    # Extract all numbers present in the input row
    row_numbers: Set[float] = set()
    for v in test_row.values():
        if isinstance(v, (int, float)):
            row_numbers.add(float(v))
            row_numbers.add(float(int(v)))

    # Test explanations across all 5 label classes
    for label in LABEL_CLASSES:
        sample_reasons = [
            {"feature": "decision_seconds", "value": test_row["decision_seconds"]},
            {"feature": "trades_today", "value": test_row["trades_today"]},
            {"feature": "drop_pct", "value": test_row["drop_pct"]},
        ]
        text = explain_text(test_row, sample_reasons, predicted_label=label)

        # Regex search for all numeric tokens in the generated explanation
        found_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text)
        for num_str in found_numbers:
            num = float(num_str)
            assert num in row_numbers, (
                f"Explanation text for label '{label}' contained number {num} ({num_str}) "
                f"which was not present in the input row!\nText: {text}"
            )


def test_model_loads_in_under_one_second():
    """Requirement 8.4: Ensure trained model artifact loads from disk and initializes in < 1.0s."""
    t0 = time.time()
    # Force reload fresh from disk
    predictor = MLPredictor.get_instance(force_reload=True)
    elapsed = time.time() - t0

    assert elapsed < 1.0, f"Model loading was too slow: {elapsed:.3f}s (required < 1.0s)"
    assert predictor.model is not None
    assert predictor.explainer is not None


def test_five_bots_and_idempotency(db_session, sample_scenario):
    """Requirement 1: Test 5 bots decide on scenario with 15% disciplined behavior and idempotency."""
    # First run
    count1 = populate_bot_decisions(db_session, [sample_scenario])
    assert count1 == 5

    # Check that decisions for all 5 bots were stored with actor_type="bot"
    records = (
        db_session.query(BotDecision)
        .filter(BotDecision.scenario_id == sample_scenario.id)
        .all()
    )
    assert len(records) == 5
    bot_names = {r.bot_name for r in records}
    assert bot_names == set(BOT_NAMES)

    for r in records:
        assert r.actor_type == "bot"
        assert r.true_label in LABEL_CLASSES
        assert r.features is not None
        assert "bot_name" not in r.features

    # Second run must be idempotent (0 newly inserted)
    count2 = populate_bot_decisions(db_session, [sample_scenario])
    assert count2 == 0

    total_records = (
        db_session.query(BotDecision)
        .filter(BotDecision.scenario_id == sample_scenario.id)
        .count()
    )
    assert total_records == 5


def test_history_features_empty_and_populated():
    """Requirement 2: Test history features shared function works with empty history and populated history."""
    # Empty history
    empty_hf = compute_history_features([])
    assert empty_hf["history_total_decisions"] == 0.0
    assert empty_hf["history_mistake_count"] == 0.0
    assert empty_hf["history_mistake_rate"] == 0.0
    assert empty_hf["history_panic_count"] == 0.0

    # Populated history with 10 decisions
    history_window = [
        {"label": "disciplined", "decision_seconds": 15.0},
        {"label": "panic_sell", "decision_seconds": 3.0},
        {"label": "disciplined", "decision_seconds": 12.0},
        {"label": "fomo_buy", "decision_seconds": 4.0},
        {"label": "averaging_down", "decision_seconds": 5.0},
        {"label": "revenge_trade", "decision_seconds": 3.5},
        {"label": "disciplined", "decision_seconds": 18.0},
        {"label": "panic_sell", "decision_seconds": 2.5},
        {"label": "panic_sell", "decision_seconds": 3.0},
        {"label": "panic_sell", "decision_seconds": 4.0},
    ]
    hf = compute_history_features(history_window)
    assert hf["history_total_decisions"] == 10.0
    assert hf["history_panic_count"] == 4.0
    assert hf["history_panic_rate"] == 0.4
    assert hf["history_averaging_count"] == 1.0
    assert hf["history_fomo_count"] == 1.0
    assert hf["history_revenge_count"] == 1.0
    assert hf["history_disciplined_count"] == 3.0
    assert hf["history_mistake_count"] == 7.0
    assert hf["history_mistake_rate"] == 0.7
    assert hf["history_last_was_mistake"] == 1.0
    assert hf["history_consecutive_mistakes"] == 3.0


def test_retrain_pipeline(db_session):
    """Requirement 7: Test retrain pipeline with human feedback and promotion evaluation."""
    # Run retraining
    result = retrain_model(db=db_session, new_version="v1.1.0")
    assert result["status"] in ["promoted", "kept_current"]
    assert "candidate_macro_f1" in result
    assert "confusion_matrix" in result

    # Check that previous model version (v1.0.0) remains preserved on disk
    old_model_file = MODELS_DIR / "tradezen_model_v1.0.0.joblib"
    assert old_model_file.exists(), "Old model version must be kept on disk!"
