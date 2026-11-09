"""ML Predictor and SHAP Explainer service for TradeZen.

- Loads trained model bundle from disk once in under 1 second.
- Creates SHAP explainer once at startup and reuses it for all predictions.
- Returns top predicted label, probabilities distribution, and top 3 SHAP reasons.
- Never shows raw SHAP float values to users.
"""

import time
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import joblib
import shap

from app.services.features import FEATURE_COLUMNS, LABEL_CLASSES

logger = logging.getLogger("tradezen.ml.predictor")

MODELS_DIR = Path(__file__).resolve().parent / "models"


class MLPredictor:
    """Singleton service for behavioral pattern prediction and SHAP feature attribution."""

    _instance: Optional["MLPredictor"] = None

    def __init__(self, model_bundle_path: Optional[Path] = None):
        t0 = time.time()
        self.model_path = model_bundle_path or self._resolve_active_model_path()
        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(f"Trained model artifact not found at {self.model_path}")

        # Load bundle from disk (< 1 second)
        self.bundle = joblib.load(self.model_path)
        self.load_time_seconds = time.time() - t0

        self.model = self.bundle["model"]
        self.model_type = self.bundle.get("model_type", "xgboost")
        self.model_version = self.bundle.get("model_version", "v1.0.0")
        self.classes: List[str] = self.bundle.get("classes", LABEL_CLASSES)
        self.feature_names: List[str] = self.bundle.get("feature_names", FEATURE_COLUMNS)

        # Create SHAP explainer once at startup
        t_explainer = time.time()
        self.explainer = self._init_explainer()
        self.explainer_init_time_seconds = time.time() - t_explainer

        logger.info(
            "MLPredictor initialized in %.3fs (load: %.3fs, explainer: %.3fs) with model %s (%s)",
            time.time() - t0,
            self.load_time_seconds,
            self.explainer_init_time_seconds,
            self.model_version,
            self.model_type,
        )

    @classmethod
    def get_instance(cls, force_reload: bool = False) -> "MLPredictor":
        """Returns or initializes singleton predictor instance."""
        if cls._instance is None or force_reload:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _resolve_active_model_path() -> Optional[Path]:
        """Resolves active model path from active_model.json or newest joblib file."""
        pointer = MODELS_DIR / "active_model.json"
        if pointer.exists():
            try:
                with open(pointer, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    fn = data.get("model_filename")
                    if fn and (MODELS_DIR / fn).exists():
                        return MODELS_DIR / fn
            except Exception as exc:
                logger.warning("Could not read active_model.json: %s", exc)

        # Fallback to any available joblib file in models directory
        joblib_files = list(MODELS_DIR.glob("*.joblib"))
        if joblib_files:
            joblib_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return joblib_files[0]

        return None

    def _init_explainer(self) -> Any:
        """Initializes the SHAP explainer once based on model type."""
        try:
            if self.model_type == "xgboost":
                return shap.TreeExplainer(self.model)
            else:
                # For LogisticRegression pipeline or linear models
                # Create a small zero/mean baseline background matrix
                background = np.zeros((1, len(self.feature_names)), dtype=np.float32)
                clf = self.model.named_steps["clf"] if hasattr(self.model, "named_steps") else self.model
                return shap.Explainer(clf, background)
        except Exception as exc:
            logger.warning("SHAP explainer init warning (%s), using tree explainer fallback", exc)
            return shap.Explainer(self.model)

    def predict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Predicts behavioural pattern, probability distribution, and top 3 SHAP reasons.

        Returns:
            {
                "label": top_label,
                "probability": float,
                "probabilities": {class: prob},
                "reasons": [{"feature": name, "value": val}, ...],
                "model_version": version_str
            }
        """
        # Prepare feature vector matching canonical order
        feature_vals = [float(row.get(col, 0.0)) for col in self.feature_names]
        X = np.array([feature_vals], dtype=np.float32)

        # 1. Probabilities and top class
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba(X)[0]
        else:
            probs = np.ones(len(self.classes)) / len(self.classes)

        top_idx = int(np.argmax(probs))
        top_label = self.classes[top_idx]
        top_prob = float(probs[top_idx])

        # 2. Extract top 3 SHAP reasons
        reasons: List[Dict[str, Any]] = []
        try:
            shap_output = self.explainer(X)
            vals = shap_output.values if hasattr(shap_output, "values") else shap_output

            if vals.ndim == 3:
                # Shape: (1, n_features, n_classes)
                class_shap = vals[0, :, top_idx]
            elif vals.ndim == 2:
                # Shape: (1, n_features)
                class_shap = vals[0, :]
            else:
                class_shap = np.array(vals).flatten()

            # Identify top 3 features with highest positive push towards this class
            pos_indices = [i for i in range(len(self.feature_names)) if class_shap[i] > 0]
            if len(pos_indices) >= 3:
                top_indices = sorted(pos_indices, key=lambda i: class_shap[i], reverse=True)[:3]
            else:
                top_indices = sorted(range(len(self.feature_names)), key=lambda i: abs(class_shap[i]), reverse=True)[:3]

            for idx in top_indices:
                feat_col = self.feature_names[idx]
                reasons.append({
                    "feature": feat_col,
                    "value": float(row.get(feat_col, 0.0)),
                })
        except Exception as exc:
            logger.warning("SHAP attribution fallback: %s", exc)
            # Fallback: identify top 3 non-zero active feature signals in row
            active_feats = [
                col for col in ["decision_seconds", "trades_today", "drop_pct", "size_pct_of_capital"]
                if float(row.get(col, 0.0)) > 0
            ]
            for col in active_feats[:3]:
                reasons.append({
                    "feature": col,
                    "value": float(row.get(col, 0.0)),
                })

        return {
            "label": top_label,
            "probability": round(top_prob, 2),
            "probabilities": {cls: round(float(p), 4) for cls, p in zip(self.classes, probs)},
            "reasons": reasons,
            "model_version": self.model_version,
        }
