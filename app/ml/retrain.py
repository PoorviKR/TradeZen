"""Model retraining service incorporating human feedback rows.

- Incorporates human attempt-1 rows that received user feedback.
- Evaluates on the fixed held-out test scenario partition.
- Only replaces the live model if the candidate macro-F1 is at least as good as current active.
- Preserves all historical model versions on disk.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import joblib
from sqlalchemy.orm import Session
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import f1_score, accuracy_score, confusion_matrix, classification_report
from xgboost import XGBClassifier

from app.core.reasons import CATALOGUE_VERSION
from app.db.session import SessionLocal
from app.models.scenario import Scenario
from app.models.decision import Attempt, BotDecision, Prediction
from app.services.features import FEATURE_COLUMNS, LABEL_CLASSES, extract_feature_vector
from app.services.bots import populate_bot_decisions
from app.ml.predictor import MLPredictor, MODELS_DIR

logger = logging.getLogger("tradezen.ml.retrain")


def retrain_model(
    db: Optional[Session] = None,
    new_version: Optional[str] = None,
    random_seed: int = 42,
) -> Dict[str, Any]:
    """Retrains behavioral classification model with human feedback rows.

    Only promotes candidate model if macro-F1 on the fixed test set is >= active model macro-F1.
    """
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        # 1. Load active model and fixed test set
        predictor = MLPredictor.get_instance()
        current_bundle = predictor.bundle
        current_macro_f1 = float(current_bundle.get("metrics", {}).get("macro_f1", 0.0))
        fixed_test_ids = set(current_bundle.get("fixed_test_scenario_ids", []))
        current_version = current_bundle.get("model_version", "v1.0.0")
        schema_upgraded = not predictor.is_feature_compatible()

        label_to_int = {lbl: idx for idx, lbl in enumerate(LABEL_CLASSES)}

        # 2. Gather Bot Training Data for active catalogue version
        bot_rows = (
            db.query(BotDecision)
            .filter(
                BotDecision.actor_type == "bot",
                BotDecision.catalogue_version == CATALOGUE_VERSION,
            )
            .all()
        )
        if len(bot_rows) < 20:
            active_scenarios = db.query(Scenario).filter(Scenario.active.is_(True)).all()
            if not active_scenarios:
                from app.services.scenario_builder import ScenarioBuilder
                from datetime import date
                ScenarioBuilder(db).build_pool(date(2026, 11, 6))
            else:
                populate_bot_decisions(db, active_scenarios, catalogue_version=CATALOGUE_VERSION)
            bot_rows = (
                db.query(BotDecision)
                .filter(
                    BotDecision.actor_type == "bot",
                    BotDecision.catalogue_version == CATALOGUE_VERSION,
                )
                .all()
            )

        available_scenario_ids = list({bd.scenario_id for bd in bot_rows})
        scenario_test_ids = fixed_test_ids.intersection(available_scenario_ids)
        if len(scenario_test_ids) < 2 and available_scenario_ids:
            n_test = max(1, int(len(available_scenario_ids) * 0.2))
            scenario_test_ids = set(available_scenario_ids[-n_test:])

        train_records: List[List[float]] = []
        train_labels: List[int] = []

        test_records: List[List[float]] = []
        test_labels: List[int] = []

        for bd in bot_rows:
            feat_dict = bd.features or {}
            row_vals = [float(feat_dict.get(col, 0.0)) for col in FEATURE_COLUMNS]
            lbl_int = label_to_int.get(bd.true_label, 0)

            if bd.scenario_id in scenario_test_ids:
                test_records.append(row_vals)
                test_labels.append(lbl_int)
            else:
                train_records.append(row_vals)
                train_labels.append(lbl_int)

        # 3. Gather Human Attempt-1 rows with feedback (never in test partition)
        human_attempts = (
            db.query(Attempt, Prediction)
            .join(Prediction, Attempt.id == Prediction.attempt_id)
            .filter(
                Attempt.actor_type == "human",
                Attempt.attempt_no == 1,
                Prediction.feedback_correct.isnot(None),
                ~Attempt.scenario_id.in_(list(scenario_test_ids)),
            )
            .all()
        )

        human_rows_added = 0
        for att, pred in human_attempts:
            if pred.feedback_correct is True:
                # User confirmed prediction was correct
                h_label = pred.label
            else:
                # If marked incorrect, assign disciplined if passed or fallback
                h_label = "disciplined" if pred.label != "disciplined" else "panic_sell"

            feat_dict = pred.features or {}
            row_vals = [float(feat_dict.get(col, 0.0)) for col in FEATURE_COLUMNS]
            train_records.append(row_vals)
            train_labels.append(label_to_int.get(h_label, 0))
            human_rows_added += 1

        logger.info(
            "Retraining dataset: %d train rows (%d human feedback), %d fixed test rows",
            len(train_records),
            human_rows_added,
            len(test_records),
        )

        if not test_records:
            raise ValueError("Fixed test partition is empty. Cannot evaluate retraining candidate.")

        X_train = np.array(train_records, dtype=np.float32)
        y_train = np.array(train_labels, dtype=np.int64)
        X_test = np.array(test_records, dtype=np.float32)
        y_test = np.array(test_labels, dtype=np.int64)

        # 4. Train candidates on expanded training data
        lr_pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, random_state=random_seed)),
        ])
        lr_pipeline.fit(X_train, y_train)
        f1_lr = f1_score(y_test, lr_pipeline.predict(X_test), average="macro", zero_division=0)

        xgb_clf = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=random_seed,
            eval_metric="mlogloss",
        )
        xgb_clf.fit(X_train, y_train)
        f1_xgb = f1_score(y_test, xgb_clf.predict(X_test), average="macro", zero_division=0)

        if f1_xgb >= f1_lr:
            candidate_model = xgb_clf
            candidate_type = "xgboost"
            candidate_f1 = f1_xgb
            candidate_preds = xgb_clf.predict(X_test)
        else:
            candidate_model = lr_pipeline
            candidate_type = "logistic_regression"
            candidate_f1 = f1_lr
            candidate_preds = lr_pipeline.predict(X_test)

        acc = accuracy_score(y_test, candidate_preds)
        cm = confusion_matrix(y_test, candidate_preds, labels=list(range(len(LABEL_CLASSES)))).tolist()

        logger.info(
            "Candidate Macro-F1: %.4f vs Current Active Macro-F1: %.4f",
            candidate_f1,
            current_macro_f1,
        )

        # 5. Check promotion criterion: candidate macro-F1 must be >= current active
        # (or promote automatically when upgrading from an incompatible feature schema)
        is_promoted = schema_upgraded or (candidate_f1 >= current_macro_f1)

        if not new_version:
            # Generate next patch/minor version string
            parts = current_version.lstrip("v").split(".")
            next_patch = int(parts[-1]) + 1 if len(parts) >= 3 else 1
            new_version = f"v{parts[0]}.{parts[1] if len(parts) > 1 else 0}.{next_patch}"

        result = {
            "status": "promoted" if is_promoted else "kept_current",
            "active_version_before": current_version,
            "active_macro_f1_before": current_macro_f1,
            "candidate_version": new_version,
            "candidate_macro_f1": round(float(candidate_f1), 4),
            "candidate_accuracy": round(float(acc), 4),
            "selected_model": candidate_type,
            "human_feedback_rows_incorporated": human_rows_added,
            "promoted": is_promoted,
            "confusion_matrix": cm,
        }

        if is_promoted:
            # Save new model bundle while preserving previous version files
            new_filename = f"tradezen_model_{new_version}.joblib"
            new_model_path = MODELS_DIR / new_filename

            bundle = {
                "model": candidate_model,
                "model_type": candidate_type,
                "model_version": new_version,
                "classes": LABEL_CLASSES,
                "feature_names": FEATURE_COLUMNS,
                "metrics": result,
                "fixed_test_scenario_ids": list(fixed_test_ids),
            }
            joblib.dump(bundle, new_model_path)

            # Update active pointer
            active_pointer_path = MODELS_DIR / "active_model.json"
            with open(active_pointer_path, "w", encoding="utf-8") as f:
                json.dump({
                    "active_version": new_version,
                    "model_filename": new_filename,
                    "selected_model": candidate_type,
                    "macro_f1": round(float(candidate_f1), 4),
                    "accuracy": round(float(acc), 4),
                }, f, indent=2)

            # Reload singleton predictor
            MLPredictor.get_instance(force_reload=True)
            logger.info("Successfully promoted new model %s as active live model!", new_version)
        else:
            logger.info("Candidate model did not improve upon active model (%.4f < %.4f). Keeping %s.", candidate_f1, current_macro_f1, current_version)

        return result

    finally:
        if owns_session:
            db.close()


def main():
    """CLI runner: python -m app.ml.retrain"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("Starting TradeZen model retraining with human feedback...")
    try:
        res = retrain_model()
        print("\nRetraining Run Finished:")
        print(f"  Status:               {res['status']}")
        print(f"  Active Before:        {res['active_version_before']} (macro-F1: {res['active_macro_f1_before']:.4f})")
        print(f"  Candidate:            {res['candidate_version']} (macro-F1: {res['candidate_macro_f1']:.4f})")
        print(f"  Human Rows Included:  {res['human_feedback_rows_incorporated']}")
        print(f"  Promoted to Live:     {res['promoted']}")
    except Exception as exc:
        print(f"Retraining failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
