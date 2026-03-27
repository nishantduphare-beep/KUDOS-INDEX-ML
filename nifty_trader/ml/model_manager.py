"""
ml/model_manager.py
─────────────────────────────────────────────────────────────────
Manages the full ML model lifecycle:
  • Checks if enough labeled data exists to train
  • Trains (or retrains) XGBoost / RandomForest
  • Versions models to disk
  • Serves predictions in real-time
  • Schedules automatic retraining as new labeled data arrives
  • Emits "model updated" events the UI can subscribe to

The system works in 3 phases:
  Phase 1: < MIN_SAMPLES_TO_TRAIN      → No ML, strategy only
  Phase 2: MIN_SAMPLES_TO_TRAIN ≤ n    → Train first model, show ML score
  Phase 3: Every RETRAIN_INTERVAL new samples → Retrain, improve

Continuous learning loop:
  AutoLabeler labels → ModelManager detects new labels → retrains → better predictions
"""

import json
import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Tuple

import numpy as np
import pandas as pd

import config
from ml.feature_store import FEATURE_COLUMNS, load_dataset, prepare_features

logger = logging.getLogger(__name__)

# ── Settings ─────────────────────────────────────────────────────
MIN_SAMPLES_TO_TRAIN = config.ML_MIN_SAMPLES_TO_ACTIVATE   # Start training after N labeled records
RETRAIN_INTERVAL     = config.ML_RETRAIN_INTERVAL_SAMPLES  # Retrain every N new labeled samples
MODEL_DIR            = Path("models")
CHECK_INTERVAL_SEC   = 300          # Check for new data every 5 minutes


# ──────────────────────────────────────────────────────────────────
# MODEL METADATA
# ──────────────────────────────────────────────────────────────────

@dataclass
class ModelVersion:
    version:       int
    trained_at:    datetime
    samples_used:  int
    model_type:    str
    metrics:       Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    feature_cols:  List[str] = field(default_factory=list)  # actual columns used during training
    is_active:     bool = True

    def to_dict(self) -> Dict:
        return {
            "version":            self.version,
            "trained_at":         self.trained_at.isoformat(),
            "samples_used":       self.samples_used,
            "model_type":         self.model_type,
            "metrics":            self.metrics,
            "is_active":          self.is_active,
            "feature_importance": self.feature_importance,  # C2 fix: was omitted — always {} after restart
            "feature_cols":       self.feature_cols,        # must match X shape at prediction time
        }


# ──────────────────────────────────────────────────────────────────
# PREDICTION RESULT
# ──────────────────────────────────────────────────────────────────

@dataclass
class MLPrediction:
    is_available:      bool    = False
    probability:       float   = 0.0      # 0.0 → 1.0
    ml_confidence:     float   = 0.0      # 0 → 100 (scaled for display)
    recommendation:    str     = "INSUFFICIENT_DATA"
    direction:         str     = "NEUTRAL"
    top_features:      Dict[str, float] = field(default_factory=dict)
    model_version:     int     = 0
    samples_used:      int     = 0
    phase:             int     = 1        # 1=no model, 2=has model
    samples_needed:    int     = 0        # samples still needed before model trains

    def __str__(self):
        if not self.is_available:
            return f"ML: collecting data ({self.samples_needed} more samples needed)"
        return (
            f"ML v{self.model_version}: "
            f"{self.recommendation} @ {self.ml_confidence:.1f}% "
            f"[{self.samples_used} samples]"
        )


# ──────────────────────────────────────────────────────────────────
# MODEL MANAGER
# ──────────────────────────────────────────────────────────────────

class ModelManager:
    """
    Central ML orchestrator. Thread-safe. Uses XGBoost by default,
    falls back to scikit-learn RandomForest if XGBoost not installed.
    """

    def __init__(self):
        self._model          = None
        self._model_version: Optional[ModelVersion] = None
        self._lock           = threading.Lock()
        self._running        = False
        self._thread:        Optional[threading.Thread] = None
        self._last_sample_count = 0
        self._callbacks:     List[Callable] = []
        self._db = None  # lazy init

        MODEL_DIR.mkdir(exist_ok=True)
        self._load_latest_model()

    # ─── Public API ───────────────────────────────────────────────

    def add_update_callback(self, fn: Callable):
        """Called when a new model version is trained."""
        self._callbacks.append(fn)

    def start_background_loop(self):
        """Start continuous learning check in background."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._check_loop, daemon=True, name="MLTrainThread"
        )
        self._thread.start()
        logger.info("ModelManager background loop started")

    def stop(self):
        self._running = False

    def predict(self, features: Dict[str, Any], direction: str) -> MLPrediction:
        """
        Return ML prediction for a given feature vector.
        Safe to call from any thread.
        """
        from database.manager import get_db
        if self._db is None:
            self._db = get_db()

        labeled_count = self._get_labeled_count()

        if labeled_count < MIN_SAMPLES_TO_TRAIN:
            return MLPrediction(
                is_available   = False,
                recommendation = "COLLECTING_DATA",
                phase          = 1,
                samples_needed = MIN_SAMPLES_TO_TRAIN - labeled_count,
            )

        with self._lock:
            if self._model is None:
                # Enough data but model not trained yet
                return MLPrediction(
                    is_available   = False,
                    recommendation = "TRAINING_PENDING",
                    phase          = 1,
                    samples_needed = 0,
                )

            try:
                prob        = self._predict_proba(features)
                confidence  = round(prob * 100, 1)
                version     = self._model_version.version if self._model_version else 0
                samples     = self._model_version.samples_used if self._model_version else 0
                top_feats   = self._get_top_features(features)

                # Recommendation based on probability + strategy direction
                if prob >= 0.70:
                    rec = f"STRONG_{direction}"
                elif prob >= 0.55:
                    rec = f"MODERATE_{direction}"
                elif prob >= 0.45:
                    rec = "WEAK_SIGNAL"
                else:
                    rec = "LOW_CONFIDENCE"

                return MLPrediction(
                    is_available   = True,
                    probability    = prob,
                    ml_confidence  = confidence,
                    recommendation = rec,
                    direction      = direction,
                    top_features   = top_feats,
                    model_version  = version,
                    samples_used   = samples,
                    phase          = 2,
                )
            except Exception as e:
                logger.error(f"Prediction error: {e}")
                return MLPrediction(is_available=False, recommendation="ERROR")

    def force_retrain(self) -> bool:
        """Trigger immediate retraining (callable from UI)."""
        return self._train()

    def get_status(self) -> Dict[str, Any]:
        labeled = self._get_labeled_count()
        return {
            "has_model":       self._model is not None,
            "phase":           2 if self._model else 1,
            "labeled_samples": labeled,
            "needed_to_train": max(0, MIN_SAMPLES_TO_TRAIN - labeled),
            "model_version":   self._model_version.version if self._model_version else 0,
            "trained_at":      self._model_version.trained_at.strftime("%d %b %H:%M")
                               if self._model_version else "—",
            "samples_used":    self._model_version.samples_used if self._model_version else 0,
            "metrics":         self._model_version.metrics if self._model_version else {},
            "feature_importance": self._model_version.feature_importance if self._model_version else {},
        }

    # ─── Training ─────────────────────────────────────────────────

    def _check_loop(self):
        """Background: check if we should retrain."""
        while self._running:
            try:
                labeled = self._get_labeled_count()

                # First training
                if self._model is None and labeled >= MIN_SAMPLES_TO_TRAIN:
                    logger.info(f"ML: {labeled} labeled samples — training first model")
                    self._train()

                # Retrain if enough new samples
                elif (self._model is not None and
                      labeled >= self._last_sample_count + RETRAIN_INTERVAL):
                    logger.info(f"ML: {labeled - self._last_sample_count} new samples — retraining")
                    self._train()

            except Exception as e:
                logger.error(f"ML check loop error: {e}")
            time.sleep(CHECK_INTERVAL_SEC)

    def _train(self) -> bool:
        """Run training pipeline and update active model."""
        df = load_dataset(labeled_only=True)
        if len(df) < MIN_SAMPLES_TO_TRAIN:
            logger.warning(f"Not enough labeled data: {len(df)}")
            return False

        # Resolve actual feature columns present in df (subset of FEATURE_COLUMNS)
        feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        X, y = prepare_features(df)
        logger.info(f"Training on {len(X)} samples, {len(feature_cols)} features")

        model, metrics, importance = self._fit_best_model(X, y, feature_cols)
        if model is None:
            return False

        version_num = (self._model_version.version + 1) if self._model_version else 1
        mv = ModelVersion(
            version       = version_num,
            trained_at    = datetime.now(),
            samples_used  = len(X),
            model_type    = type(model).__name__,
            metrics       = metrics,
            feature_importance = importance,
            feature_cols  = feature_cols,   # store so _predict_proba uses the same shape
        )

        with self._lock:
            self._model         = model
            self._model_version = mv
            self._last_sample_count = len(X)

        self._save_model(model, mv)
        logger.info(f"Model v{version_num} trained: F1={metrics.get('f1', 0):.3f} "
                    f"Precision={metrics.get('precision', 0):.3f}")

        # Notify UI
        for cb in self._callbacks:
            try:
                cb(mv)
            except Exception:
                pass
        return True

    def _fit_best_model(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_cols: List[str],
    ):
        """Try XGBoost first, fall back to RandomForest.

        feature_cols must match the columns used to build X so that
        feature importance values are correctly labelled.
        """
        from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

        # Temporal split: train on older 80%, test on newer 20%
        # This avoids lookahead bias — model is evaluated on data it never saw
        split_idx = int(len(X) * 0.8)
        X_tr, X_te = X[:split_idx], X[split_idx:]
        y_tr, y_te = y[:split_idx], y[split_idx:]

        # Class imbalance: weight positive class higher when rare
        pos  = int(y_tr.sum())
        neg  = len(y_tr) - pos
        scale_pos = round(neg / max(pos, 1), 2)

        model      = None
        importance = {}

        # Try XGBoost
        try:
            import xgboost as xgb
            model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="logloss",
                scale_pos_weight=scale_pos,
                verbosity=0,
            )
            model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)
            importance = dict(zip(feature_cols, model.feature_importances_.tolist()))
            logger.info(f"Trained XGBoost model (scale_pos_weight={scale_pos})")
        except ImportError:
            # Fall back to RandomForest
            try:
                from sklearn.ensemble import RandomForestClassifier
                model = RandomForestClassifier(
                    n_estimators=300,
                    max_depth=6,
                    min_samples_leaf=3,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=42,
                )
                model.fit(X_tr, y_tr)
                importance = dict(zip(feature_cols, model.feature_importances_.tolist()))
                logger.info("Trained RandomForest model (XGBoost not installed)")
            except ImportError:
                logger.error("No ML library available. Install: pip install xgboost scikit-learn")
                return None, {}, {}

        if model is None:
            return None, {}, {}

        preds = model.predict(X_te)
        probs = model.predict_proba(X_te)[:, 1]

        metrics = {
            "f1":        round(float(f1_score(y_te, preds, zero_division=0)), 4),
            "precision": round(float(precision_score(y_te, preds, zero_division=0)), 4),
            "recall":    round(float(recall_score(y_te, preds, zero_division=0)), 4),
            "roc_auc":   round(float(roc_auc_score(y_te, probs)) if len(set(y_te)) > 1 else 0.5, 4),
            "samples":   len(X),
            "pos_samples": pos,
            "neg_samples": neg,
        }

        # Sort feature importance descending
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
        return model, metrics, importance

    def _predict_proba(self, features: Dict[str, Any]) -> float:
        """Run model inference using the same feature columns the model was trained on.

        CRITICAL: must use self._model_version.feature_cols (the subset actually present
        in training data) not the full FEATURE_COLUMNS list. If a column was missing
        from the DB when training ran, that column was excluded from X — using a different
        column set here would cause a dimension mismatch and a silent prediction failure.
        """
        cols = (
            self._model_version.feature_cols
            if self._model_version and self._model_version.feature_cols
            else FEATURE_COLUMNS
        )
        row = np.array([[features.get(c, 0.0) for c in cols]], dtype=np.float32)
        proba = self._model.predict_proba(row)[0]
        return float(proba[1]) if len(proba) > 1 else float(proba[0])

    def _get_top_features(self, features: Dict, top_n: int = 5) -> Dict[str, float]:
        """Return top N feature contributions for explainability."""
        if self._model_version is None:
            return {}
        importance = self._model_version.feature_importance
        top = {}
        for feat in list(importance.keys())[:top_n]:
            val = features.get(feat, 0.0)
            top[feat] = round(float(val), 4)
        return top

    # ─── Persistence ──────────────────────────────────────────────

    def _save_model(self, model, mv: ModelVersion):
        try:
            path = MODEL_DIR / f"model_v{mv.version}.pkl"
            with open(path, "wb") as f:
                pickle.dump(model, f)

            meta_path = MODEL_DIR / f"model_v{mv.version}_meta.json"
            meta_path.write_text(json.dumps(mv.to_dict(), indent=2))

            # Update "latest" symlink equivalent
            latest = MODEL_DIR / "latest.pkl"
            with open(latest, "wb") as f:
                pickle.dump(model, f)
            (MODEL_DIR / "latest_meta.json").write_text(
                json.dumps(mv.to_dict(), indent=2)
            )
            logger.info(f"Model v{mv.version} saved → {path}")
        except Exception as e:
            logger.error(f"Model save error: {e}")

    def _load_latest_model(self):
        try:
            latest     = MODEL_DIR / "latest.pkl"
            meta_path  = MODEL_DIR / "latest_meta.json"
            if not latest.exists():
                return

            with open(latest, "rb") as f:
                self._model = pickle.load(f)

            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                self._model_version = ModelVersion(
                    version       = meta["version"],
                    trained_at    = datetime.fromisoformat(meta["trained_at"]),
                    samples_used  = meta["samples_used"],
                    model_type    = meta.get("model_type", "Unknown"),
                    metrics       = meta.get("metrics", {}),
                    feature_importance = meta.get("feature_importance", {}),
                    feature_cols  = meta.get("feature_cols", []),  # [] → fallback to FEATURE_COLUMNS
                )
                self._last_sample_count = self._model_version.samples_used
                logger.info(
                    f"Loaded model v{self._model_version.version} "
                    f"({self._model_version.samples_used} samples, "
                    f"{self._model_version.model_type})"
                )
        except Exception as e:
            logger.warning(f"Could not load saved model: {e}")
            self._model = None

    # ─── Helpers ──────────────────────────────────────────────────

    # ─── Report Generation ────────────────────────────────────────

    def generate_report(self) -> Dict[str, Any]:
        """
        Analyse labeled data and return actionable config suggestions.

        Returns dict with:
          - feature_importance   : ranked features
          - threshold_analysis   : precision/recall/F1 at thresholds 3-6
          - recommended_threshold: optimal MIN_ENGINES value
          - best_time_window     : IST hour range with highest accuracy
          - best_index           : NIFTY / BANKNIFTY / MIDCPNIFTY
          - suggested_config     : dict of config key → suggested value
          - summary_text         : human-readable summary
        """
        df = load_dataset(labeled_only=True)
        if len(df) < 30:
            return {
                "error": f"Need at least 30 labeled samples (have {len(df)}). "
                         "Label alerts in the Alerts tab first.",
                "samples": len(df),
            }

        report: Dict[str, Any] = {"samples": len(df)}

        # ── Feature importance ────────────────────────────────────
        if self._model_version and self._model_version.feature_importance:
            fi = self._model_version.feature_importance
        else:
            fi = {}
        report["feature_importance"] = fi

        # ── Threshold analysis ────────────────────────────────────
        thresh_results = {}
        if "engines_count" in df.columns and "label" in df.columns:
            from sklearn.metrics import precision_score, recall_score, f1_score
            for th in (3, 4, 5, 6):
                # Simulate: threshold fires when engines_count >= th
                fired = (df["engines_count"] >= th).astype(int)
                truth = (df["label"] == 1).astype(int)
                fired_mask = fired == 1
                n_fired = fired_mask.sum()
                if n_fired == 0:
                    thresh_results[th] = {"precision": 0, "recall": 0, "f1": 0,
                                          "signals": 0}
                    continue
                p = precision_score(truth[fired_mask], fired[fired_mask],
                                    zero_division=0)
                r = recall_score(truth, fired, zero_division=0)
                f = f1_score(truth, fired, zero_division=0)
                thresh_results[th] = {
                    "precision": round(float(p), 3),
                    "recall":    round(float(r), 3),
                    "f1":        round(float(f), 3),
                    "signals":   int(n_fired),
                }
        report["threshold_analysis"] = thresh_results

        # ── Best threshold (highest F1) ───────────────────────────
        if thresh_results:
            best_th = max(thresh_results, key=lambda t: thresh_results[t].get("f1", 0))
        else:
            best_th = config.MIN_ENGINES_FOR_ALERT
        report["recommended_threshold"] = best_th

        # ── Best time window ──────────────────────────────────────
        best_hour = 10
        if "timestamp" in df.columns:
            try:
                df["_hour"] = pd.to_datetime(df["timestamp"]).dt.hour
                hour_acc = (
                    df.groupby("_hour")["label"]
                    .apply(lambda s: (s == 1).mean())
                    .to_dict()
                )
                if hour_acc:
                    best_hour = max(hour_acc, key=hour_acc.get)
                report["hour_accuracy"] = {
                    f"{h:02d}:00": round(float(v), 3)
                    for h, v in hour_acc.items()
                }
            except Exception:
                pass
        report["best_time_window"] = f"{best_hour:02d}:00–{best_hour+2:02d}:00 IST"

        # ── Best index ────────────────────────────────────────────
        best_index = "NIFTY"
        if "index_name" in df.columns:
            try:
                idx_acc = (
                    df.groupby("index_name")["label"]
                    .apply(lambda s: (s == 1).mean())
                    .to_dict()
                )
                if idx_acc:
                    best_index = max(idx_acc, key=idx_acc.get)
                report["index_accuracy"] = {
                    k: round(float(v), 3) for k, v in idx_acc.items()
                }
            except Exception:
                pass
        report["best_index"] = best_index

        # ── Top engine combinations ────────────────────────────────
        trigger_cols = [c for c in df.columns if c.endswith("_triggered")]
        if trigger_cols and "label" in df.columns:
            try:
                engine_win_rates = {}
                for col in trigger_cols:
                    eng_name = col.replace("_triggered", "")
                    mask = df[col] == True
                    if mask.sum() > 5:
                        win_rate = (df.loc[mask, "label"] == 1).mean()
                        engine_win_rates[eng_name] = round(float(win_rate), 3)
                report["engine_win_rates"] = dict(
                    sorted(engine_win_rates.items(), key=lambda x: x[1], reverse=True)
                )
            except Exception:
                pass

        # ── Suggested config ──────────────────────────────────────
        suggested = {"MIN_ENGINES_FOR_ALERT": best_th}

        # If a particular index is much better, flag it
        idx_acc = report.get("index_accuracy", {})
        if idx_acc:
            best_acc  = max(idx_acc.values())
            worst_acc = min(idx_acc.values())
            if best_acc - worst_acc > 0.15:
                suggested["FOCUS_INDEX"] = best_index

        # Top 3 features — suggest adjusting their thresholds
        if fi:
            top_feats = list(fi.keys())[:3]
            suggested["TOP_FEATURES"] = top_feats

        report["suggested_config"] = suggested

        # ── Human-readable summary ─────────────────────────────────
        th_info = thresh_results.get(best_th, {})
        lines = [
            f"Analyzed {len(df)} labeled signals.",
            f"Best threshold: {best_th}+ engines  "
            f"(Precision={th_info.get('precision',0):.0%}  "
            f"Recall={th_info.get('recall',0):.0%}  "
            f"F1={th_info.get('f1',0):.2f})",
            f"Best index: {best_index}  |  Best time: {report['best_time_window']}",
        ]
        if fi:
            top3 = list(fi.keys())[:3]
            lines.append(f"Top features: {', '.join(top3)}")
        report["summary_text"] = "\n".join(lines)

        return report

    def _get_labeled_count(self) -> int:
        try:
            from database.manager import get_db
            if self._db is None:
                self._db = get_db()
            with self._db.get_session() as session:
                from database.models import MLFeatureRecord
                return session.query(MLFeatureRecord).filter(
                    MLFeatureRecord.label != -1
                ).count()
        except Exception:
            return 0


# ── Global singleton ─────────────────────────────────────────────
_manager: Optional[ModelManager] = None
_manager_lock = threading.Lock()


def get_model_manager() -> ModelManager:
    """Return the process-wide ModelManager singleton. Thread-safe (double-checked locking)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ModelManager()
    return _manager
