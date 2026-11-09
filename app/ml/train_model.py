"""Offline and scheduled model training pipeline for TradeZen.

- Uses only features known at decision time (from app.services.features).
- Strictly excludes bot_name, true_label, IDs, and future outcomes.
- Splits by scenario_id 80/20 (no scenario ever appears in both sets).
- Trains LogisticRegression (baseline) and XGBoost.
- Selects the superior model by macro-F1 score on the held-out scenario test set.
- Saves the model bundle, model_version, evaluation metrics, and confusion matrix.
"""

import os
import sys
import json
import random
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import joblib

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import f1_score, accuracy_score, confusion_matrix, classification_report
from xgboost import XGBClassifier
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.scenario import Scenario
from app.models.decision import BotDecision
from app.services.features import FEATURE_COLUMNS, LABEL_CLASSES
from app.services.bots import populate_bot_decisions

logger = logging.getLogger("tradezen.ml.train")

MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def train_model(
    db: Optional[Session] = None,
    model_version: str = "v1.0.0",
    random_seed: int = 42,
) -> Dict[str, Any]:
    """Trains and selects the best behavioral classification model (XGBoost vs LogisticRegression).

    Returns summary metrics dictionary.
    """
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        # 1. Fetch bot decisions
        bot_rows = (
            db.query(BotDecision)
            .filter(BotDecision.actor_type == "bot")
            .all()
        )

        # If no bot decisions exist yet, attempt to populate them
        if len(bot_rows) < 50:
            logger.info("Bot decision rows (%d) low. Checking active scenarios to populate...", len(bot_rows))
            populate_bot_decisions(db)
            bot_rows = (
                db.query(BotDecision)
                .filter(BotDecision.actor_type == "bot")
                .all()
            )

        if len(bot_rows) < 10:
            raise ValueError(
                f"Insufficient training data: only {len(bot_rows)} bot decision rows found. "
                "Please run scenario refresh and bot generation first."
            )

        # 2. Assemble dataset
        records = []
        labels = []
        scenario_ids = []

        label_to_int = {lbl: idx for idx, lbl in enumerate(LABEL_CLASSES)}

        for bd in bot_rows:
            feat_dict = bd.features or {}
            # Verify no bot_name leakage in features
            assert "bot_name" not in feat_dict, "Data leakage detected: bot_name present in features!"
            assert "true_label" not in feat_dict, "Data leakage detected: true_label present in features!"

            # Extract row matching canonical order
            row_vals = [float(feat_dict.get(col, 0.0)) for col in FEATURE_COLUMNS]
            records.append(row_vals)
            labels.append(label_to_int.get(bd.true_label, 0))
            scenario_ids.append(bd.scenario_id)

        X = np.array(records, dtype=np.float32)
        y = np.array(labels, dtype=np.int64)
        scenarios_arr = np.array(scenario_ids)

        # 3. Split by scenario_id 80/20 (One scenario must never be in both sets)
        unique_scenarios = list(np.unique(scenarios_arr))
        rng = random.Random(random_seed)
        rng.shuffle(unique_scenarios)

        n_train_scenarios = max(1, int(len(unique_scenarios) * 0.8))
        train_scenario_set = set(unique_scenarios[:n_train_scenarios])
        test_scenario_set = set(unique_scenarios[n_train_scenarios:])

        train_mask = np.isin(scenarios_arr, list(train_scenario_set))
        test_mask = np.isin(scenarios_arr, list(test_scenario_set))

        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]

        logger.info(
            "Split by scenario: %d train scenarios (%d rows), %d test scenarios (%d rows)",
            len(train_scenario_set),
            len(X_train),
            len(test_scenario_set),
            len(X_test),
        )

        # 4. Train Baseline: Logistic Regression
        lr_pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, random_state=random_seed)),
        ])
        lr_pipeline.fit(X_train, y_train)
        y_pred_lr = lr_pipeline.predict(X_test)
        f1_lr = f1_score(y_test, y_pred_lr, average="macro", zero_division=0)
        acc_lr = accuracy_score(y_test, y_pred_lr)

        # 5. Train Challenger: XGBoost
        xgb_clf = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=random_seed,
            eval_metric="mlogloss",
        )
        xgb_clf.fit(X_train, y_train)
        y_pred_xgb = xgb_clf.predict(X_test)
        f1_xgb = f1_score(y_test, y_pred_xgb, average="macro", zero_division=0)
        acc_xgb = accuracy_score(y_test, y_pred_xgb)

        logger.info(
            "Evaluation Macro-F1 - LogisticRegression: %.4f | XGBoost: %.4f",
            f1_lr,
            f1_xgb,
        )

        # 6. Keep the better model by macro-F1
        if f1_xgb >= f1_lr:
            selected_model = xgb_clf
            selected_type = "xgboost"
            best_f1 = f1_xgb
            best_acc = acc_xgb
            best_preds = y_pred_xgb
        else:
            selected_model = lr_pipeline
            selected_type = "logistic_regression"
            best_f1 = f1_lr
            best_acc = acc_lr
            best_preds = y_pred_lr

        # Compute confusion matrix
        cm = confusion_matrix(y_test, best_preds, labels=list(range(len(LABEL_CLASSES)))).tolist()
        report = classification_report(
            y_test,
            best_preds,
            target_names=LABEL_CLASSES,
            output_dict=True,
            zero_division=0,
        )

        metrics = {
            "model_version": model_version,
            "selected_model": selected_type,
            "macro_f1": round(float(best_f1), 4),
            "accuracy": round(float(best_acc), 4),
            "logistic_regression_macro_f1": round(float(f1_lr), 4),
            "xgboost_macro_f1": round(float(f1_xgb), 4),
            "confusion_matrix": cm,
            "classification_report": report,
            "classes": LABEL_CLASSES,
            "feature_names": FEATURE_COLUMNS,
            "n_train_samples": int(len(X_train)),
            "n_test_samples": int(len(X_test)),
            "n_train_scenarios": int(len(train_scenario_set)),
            "n_test_scenarios": int(len(test_scenario_set)),
            "fixed_test_scenario_ids": [int(s) for s in test_scenario_set],
        }

        # 7. Save model artifact and metadata
        model_filename = f"tradezen_model_{model_version}.joblib"
        model_path = MODELS_DIR / model_filename

        bundle = {
            "model": selected_model,
            "model_type": selected_type,
            "model_version": model_version,
            "classes": LABEL_CLASSES,
            "feature_names": FEATURE_COLUMNS,
            "metrics": metrics,
            "fixed_test_scenario_ids": [int(s) for s in test_scenario_set],
        }
        joblib.dump(bundle, model_path)
        logger.info("Saved trained model bundle to %s", model_path)

        # Save metrics json
        metrics_path = MODELS_DIR / f"metrics_{model_version}.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        # Update active_model.json pointer
        active_pointer_path = MODELS_DIR / "active_model.json"
        with open(active_pointer_path, "w", encoding="utf-8") as f:
            json.dump({
                "active_version": model_version,
                "model_filename": model_filename,
                "selected_model": selected_type,
                "macro_f1": round(float(best_f1), 4),
                "accuracy": round(float(best_acc), 4),
            }, f, indent=2)

        logger.info("Active model updated to version %s (%s, macro-F1: %.4f)", model_version, selected_type, best_f1)
        return metrics

    finally:
        if owns_session:
            db.close()


def main():
    """CLI runner: python -m app.ml.train_model"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("Starting TradeZen behavioral pattern model training...")
    try:
        metrics = train_model()
        print("\nModel Training Completed Successfully:")
        print(f"  Model Version:    {metrics['model_version']}")
        print(f"  Selected Model:   {metrics['selected_model']}")
        print(f"  Macro-F1 Score:   {metrics['macro_f1']:.4f}")
        print(f"  Accuracy:         {metrics['accuracy']:.4f}")
        print(f"  LR Baseline F1:   {metrics['logistic_regression_macro_f1']:.4f}")
        print(f"  XGBoost F1:       {metrics['xgboost_macro_f1']:.4f}")
        print(f"  Train Samples:    {metrics['n_train_samples']} ({metrics['n_train_scenarios']} scenarios)")
        print(f"  Test Samples:     {metrics['n_test_samples']} ({metrics['n_test_scenarios']} scenarios)")
        print("  Confusion Matrix:")
        for row in metrics['confusion_matrix']:
            print(f"    {row}")
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
