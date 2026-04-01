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
from ml.readiness_checker import MLReadinessChecker, ReadinessReport

logger = logging.getLogger(__name__)

# ── Settings ─────────────────────────────────────────────────────
MIN_SAMPLES_TO_TRAIN = config.ML_MIN_SAMPLES_TO_ACTIVATE   # Start training after N labeled records
RETRAIN_INTERVAL     = config.ML_RETRAIN_INTERVAL_SAMPLES  # Retrain every N new labeled samples
MODEL_DIR            = Path(__file__).parent.parent / "models"
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
    # Training distribution: {feature_name: [mean, std]} for drift detection (Item 7)
    training_stats: Dict[str, List[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "version":            self.version,
            "trained_at":         self.trained_at.isoformat(),
            "samples_used":       self.samples_used,
            "model_type":         self.model_type,
            "metrics":            self.metrics,
            "is_active":          self.is_active,
            "feature_importance": self.feature_importance,
            "feature_cols":       self.feature_cols,
            "training_stats":     self.training_stats,     # {feat: [mean, std]} for drift detection
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

    # Minimum samples required per index to train an index-specific model.
    # Below this, the global model is used as fallback.
    _MIN_INDEX_SAMPLES = 80

    def __init__(self):
        # ── Global model (trained on all indices) ──────────────
        self._model          = None
        self._model_version: Optional[ModelVersion] = None
        # ── Per-index models (Item 4) ───────────────────────────
        # Key = index_name ("NIFTY", "BANKNIFTY", etc.)
        # Value = (model_object, ModelVersion)
        self._index_models:   Dict[str, Any]           = {}
        self._index_versions: Dict[str, ModelVersion]  = {}
        self._index_sample_counts: Dict[str, int]      = {}

        self._lock           = threading.Lock()
        self._running        = False
        self._thread:        Optional[threading.Thread] = None
        self._last_sample_count = 0
        self._callbacks:     List[Callable] = []
        self._db = None  # lazy init
        self._last_readiness: Optional[ReadinessReport] = None

        MODEL_DIR.mkdir(exist_ok=True)
        self._load_latest_model()
        self._load_index_models()

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

    def predict(self, features: Dict[str, Any], direction: str,
               index_name: str = "") -> MLPrediction:
        """
        Return ML prediction for a given feature vector.
        Safe to call from any thread.

        Item 4: if a per-index model exists for index_name with sufficient
        training data, it is preferred over the global model. This gives
        sharper predictions for indices with distinct volatility profiles.
        Falls back to global model when no per-index model is available.
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
            # ── Select best model for this index ─────────────────
            # Prefer per-index model if available; fall back to global.
            use_index_model = (
                index_name
                and index_name in self._index_models
                and self._index_models[index_name] is not None
            )
            active_model   = self._index_models.get(index_name) if use_index_model else self._model
            active_version = self._index_versions.get(index_name) if use_index_model else self._model_version

            if active_model is None:
                return MLPrediction(
                    is_available   = False,
                    recommendation = "TRAINING_PENDING",
                    phase          = 1,
                    samples_needed = 0,
                )

            try:
                prob       = self._predict_proba(features, active_model, active_version)
                confidence = round(prob * 100, 1)
                version    = active_version.version if active_version else 0
                samples    = active_version.samples_used if active_version else 0
                top_feats  = self._get_top_features(features, active_version)
                model_tag  = f"{index_name}_v{version}" if use_index_model else f"global_v{version}"

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
                logger.error(f"Prediction error [{index_name or 'global'}]: {e}")
                return MLPrediction(is_available=False, recommendation="ERROR")

    def force_retrain(self) -> bool:
        """Trigger immediate retraining (callable from UI)."""
        return self._train()

    def check_readiness(self) -> ReadinessReport:
        """
        Run ML readiness check and return report.
        Logs full report at INFO level. Callable from UI or at any time.
        """
        from database.manager import get_db
        if self._db is None:
            self._db = get_db()
        metrics = self._model_version.metrics if self._model_version else None
        checker = MLReadinessChecker(self._db)
        report  = checker.check(model_metrics=metrics)
        self._last_readiness = report
        logger.info(report.full_report())
        return report

    def get_status(self) -> Dict[str, Any]:
        labeled = self._get_labeled_count()
        r = self._last_readiness
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
            # Readiness report (last check — None if check_readiness() not yet called)
            "readiness": {
                "is_ready":            r.is_ready if r else None,
                "high_quality_pct":    r.high_quality_pct if r else None,
                "atr_heuristic_pct":   r.atr_heuristic_pct if r else None,
                "core_fill_pct":       r.core_fill_pct if r else None,
                "options_fill_pct":    r.options_fill_pct if r else None,
                "win_rate_pct":        r.win_rate_pct if r else None,
                "recommended_gate":    r.recommended_gate_threshold if r else None,
                "issue_count":         len(r.issues) if r else 0,
                "error_count":         sum(1 for i in r.issues if i.severity == "ERROR") if r else 0,
            },
            # Per-index model status (Item 4)
            "index_models": {
                idx: {
                    "has_model":    idx in self._index_models,
                    "version":      self._index_versions[idx].version
                                    if idx in self._index_versions else 0,
                    "samples_used": self._index_versions[idx].samples_used
                                    if idx in self._index_versions else 0,
                    "f1":           self._index_versions[idx].metrics.get("f1", 0)
                                    if idx in self._index_versions else 0,
                    "auc":          self._index_versions[idx].metrics.get("auc", 0)
                                    if idx in self._index_versions else 0,
                }
                for idx in config.INDICES
            },
        }

    # ─── Training ─────────────────────────────────────────────────

    def _check_loop(self):
        """Background: check if we should retrain global + per-index models."""
        while self._running:
            try:
                labeled = self._get_labeled_count()

                # Global model
                if self._model is None and labeled >= MIN_SAMPLES_TO_TRAIN:
                    logger.info(f"ML: {labeled} labeled samples — training first global model")
                    self._train()
                elif (self._model is not None and
                      labeled >= self._last_sample_count + RETRAIN_INTERVAL):
                    logger.info(f"ML: {labeled - self._last_sample_count} new samples — retraining global")
                    self._train()

                # Per-index models (Item 4)
                for idx in config.INDICES:
                    self._check_index_model(idx)

            except Exception as e:
                logger.error(f"ML check loop error: {e}")
            time.sleep(CHECK_INTERVAL_SEC)

    def _check_index_model(self, index_name: str):
        """Train or retrain per-index model if enough new labeled samples exist."""
        try:
            idx_labeled = self._get_labeled_count(index_name=index_name)
            last_count  = self._index_sample_counts.get(index_name, 0)
            idx_model   = self._index_models.get(index_name)

            if idx_model is None and idx_labeled >= self._MIN_INDEX_SAMPLES:
                logger.info(f"ML [{index_name}]: {idx_labeled} samples — training first index model")
                self._train_index(index_name)
            elif (idx_model is not None and
                  idx_labeled >= last_count + RETRAIN_INTERVAL):
                logger.info(f"ML [{index_name}]: {idx_labeled - last_count} new samples — retraining")
                self._train_index(index_name)
        except Exception as e:
            logger.error(f"ML index check [{index_name}]: {e}")

    def _train(self) -> bool:
        """Run training pipeline and update active model."""
        # Run readiness check before training — logs issues but does not block.
        # Training always proceeds; readiness report is informational for the user.
        try:
            from database.manager import get_db
            if self._db is None:
                self._db = get_db()
            metrics  = self._model_version.metrics if self._model_version else None
            checker  = MLReadinessChecker(self._db)
            report   = checker.check(model_metrics=metrics)
            self._last_readiness = report
            if not report.is_ready:
                errors = [i for i in report.issues if i.severity == "ERROR"]
                for err in errors:
                    logger.warning(f"MLReadiness [{err.code}]: {err.message}")
        except Exception as _re:
            logger.debug(f"Readiness pre-check failed (non-fatal): {_re}")

        df = load_dataset(labeled_only=True)
        if len(df) < MIN_SAMPLES_TO_TRAIN:
            logger.warning(f"Not enough labeled data: {len(df)}")
            return False

        # Resolve actual feature columns present in df (subset of FEATURE_COLUMNS)
        feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        X, y = prepare_features(df)
        logger.info(f"Training on {len(X)} samples, {len(feature_cols)} features")

        # ── Item 5: sample weights by label source quality ────────
        # P1 (real TradeOutcome) = 3×, P2 (CrossLink) = 2×, P3 (OptionChain) = 1.5×,
        # P4 (ATR heuristic) = 1× (weakest), 0/unknown (legacy) = 1×.
        sample_weights: Optional[np.ndarray] = None
        if "label_source" in df.columns:
            _source_weight = {0: 1.0, 1: 3.0, 2: 2.0, 3: 1.5, 4: 1.0}
            sample_weights = np.array(
                [_source_weight.get(int(s), 1.0) for s in df["label_source"].fillna(0)],
                dtype=np.float32
            )

        model, metrics, importance, training_stats = self._fit_best_model(
            X, y, feature_cols, sample_weights
        )
        if model is None:
            return False

        version_num = (self._model_version.version + 1) if self._model_version else 1
        mv = ModelVersion(
            version        = version_num,
            trained_at     = datetime.now(),
            samples_used   = len(X),
            model_type     = type(model).__name__,
            metrics        = metrics,
            feature_importance = importance,
            feature_cols   = feature_cols,
            training_stats = training_stats,   # Item 7: drift detection baseline
        )

        with self._lock:
            self._model         = model
            self._model_version = mv
            self._last_sample_count = len(X)

        self._save_model(model, mv)
        logger.info(
            f"Model v{version_num} trained: "
            f"F1={metrics.get('f1', 0):.3f} "
            f"Precision={metrics.get('precision', 0):.3f} "
            f"AUC={metrics.get('auc', 0):.3f} "
            f"WF_F1={metrics.get('wf_f1', 0):.3f} "
            f"calibrated={metrics.get('calibrated', False)}"
        )

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
        sample_weights: Optional[np.ndarray] = None,
    ) -> Tuple:
        """
        Train best available model (XGBoost → RandomForest fallback).

        Enhancements over baseline:
          Item 2: Platt calibration — wraps model with CalibratedClassifierCV so
                  predicted probabilities map to true win frequencies.
          Item 5: sample_weights — P1 labels (real trades) outweigh P4 ATR heuristic.
          Item 7: training_stats — stores per-feature [mean, std] for drift detection.
          Item 8: walk-forward CV — 3-fold temporal CV for honest accuracy estimates.

        Returns (calibrated_model, metrics, importance, training_stats).
        """
        from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
        from sklearn.calibration import CalibratedClassifierCV

        # ── Temporal split (80/20) for final evaluation ───────────
        split_idx = int(len(X) * 0.8)
        X_tr, X_te = X[:split_idx], X[split_idx:]
        y_tr, y_te = y[:split_idx], y[split_idx:]
        w_tr = sample_weights[:split_idx] if sample_weights is not None else None

        pos  = int(y_tr.sum())
        neg  = len(y_tr) - pos
        scale_pos = round(neg / max(pos, 1), 2)

        base_model = None
        importance = {}

        # ── Train base model ──────────────────────────────────────
        try:
            import xgboost as xgb
            base_model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="logloss",
                scale_pos_weight=scale_pos,
                verbosity=0,
            )
            base_model.fit(X_tr, y_tr,
                           sample_weight=w_tr,
                           eval_set=[(X_te, y_te)], verbose=False)
            importance = dict(zip(feature_cols, base_model.feature_importances_.tolist()))
            logger.info(f"Trained XGBoost base model (scale_pos={scale_pos}, "
                        f"weighted={'yes' if w_tr is not None else 'no'})")
        except ImportError:
            try:
                from sklearn.ensemble import RandomForestClassifier
                base_model = RandomForestClassifier(
                    n_estimators=300,
                    max_depth=6,
                    min_samples_leaf=3,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=42,
                )
                base_model.fit(X_tr, y_tr, sample_weight=w_tr)
                importance = dict(zip(feature_cols, base_model.feature_importances_.tolist()))
                logger.info("Trained RandomForest base model (XGBoost not installed)")
            except ImportError:
                logger.error("No ML library. Install: pip install xgboost scikit-learn")
                return None, {}, {}, {}

        if base_model is None:
            return None, {}, {}, {}

        # ── Item 2: Platt calibration ─────────────────────────────
        # Wraps base model so predict_proba() outputs calibrated frequencies.
        # FrozenEstimator(base_model) tells sklearn the estimator is pre-fitted;
        # cv=None means use the estimator as-is (replaces deprecated cv='prefit').
        try:
            try:
                from sklearn.frozen import FrozenEstimator
                calibrated = CalibratedClassifierCV(
                    FrozenEstimator(base_model), method="sigmoid", cv=None
                )
            except ImportError:
                # sklearn < 1.6 — fall back to legacy cv='prefit'
                calibrated = CalibratedClassifierCV(
                    base_model, method="sigmoid", cv="prefit"
                )
            calibrated.fit(X_te, y_te)  # fit calibration layer on held-out set
            model = calibrated
            logger.info("Platt calibration applied (CalibratedClassifierCV sigmoid)")
        except Exception as _ce:
            logger.warning(f"Calibration failed ({_ce}) — using uncalibrated model")
            model = base_model

        # ── Item 8: Walk-forward CV metrics ──────────────────────
        # 3-fold temporal walk-forward: each fold trains on all prior data,
        # tests on the next chunk. Gives honest accuracy across time periods.
        wf_metrics = self._walk_forward_metrics(X, y, sample_weights, feature_cols)

        # ── Final metrics on temporal hold-out ───────────────────
        preds = model.predict(X_te)
        probs = model.predict_proba(X_te)[:, 1]
        metrics = {
            "f1":        round(float(f1_score(y_te, preds, zero_division=0)), 4),
            "precision": round(float(precision_score(y_te, preds, zero_division=0)), 4),
            "recall":    round(float(recall_score(y_te, preds, zero_division=0)), 4),
            "roc_auc":   round(float(roc_auc_score(y_te, probs)) if len(set(y_te)) > 1 else 0.5, 4),
            "accuracy":  round(float((preds == y_te).mean()), 4),
            "auc":       round(float(roc_auc_score(y_te, probs)) if len(set(y_te)) > 1 else 0.5, 4),
            "samples":   len(X),
            "pos_samples": pos,
            "neg_samples": neg,
            "calibrated": True,
            # Walk-forward CV averages
            "wf_f1":        round(wf_metrics.get("f1", 0.0), 4),
            "wf_precision": round(wf_metrics.get("precision", 0.0), 4),
            "wf_recall":    round(wf_metrics.get("recall", 0.0), 4),
            "wf_auc":       round(wf_metrics.get("auc", 0.0), 4),
        }

        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

        # ── Item 7: Training distribution for drift detection ────
        training_stats: Dict[str, List[float]] = {}
        for i, col in enumerate(feature_cols):
            col_vals = X[:, i]
            col_vals = col_vals[col_vals != 0]   # exclude zero-fill from stats
            if len(col_vals) >= 10:
                training_stats[col] = [
                    round(float(np.mean(col_vals)), 4),
                    round(float(np.std(col_vals)), 4),
                ]

        return model, metrics, importance, training_stats

    def _walk_forward_metrics(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weights: Optional[np.ndarray],
        feature_cols: List[str],
        n_folds: int = 3,
    ) -> Dict[str, float]:
        """
        Item 8: Temporal walk-forward cross-validation.
        Trains on older data, tests on next fold. Returns averaged metrics.
        Requires at least n_folds × 30 samples per fold to be meaningful.
        """
        from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

        n = len(X)
        min_train = 60
        if n < min_train * (n_folds + 1):
            return {}   # not enough data for walk-forward

        fold_size = n // (n_folds + 1)
        f1s, precs, recs, aucs = [], [], [], []

        for fold in range(n_folds):
            train_end = fold_size * (fold + 1)
            test_end  = train_end + fold_size
            if test_end > n:
                break
            X_tr, y_tr = X[:train_end], y[:train_end]
            X_te, y_te = X[train_end:test_end], y[train_end:test_end]
            w_tr = sample_weights[:train_end] if sample_weights is not None else None

            if len(set(y_te)) < 2:
                continue  # skip fold with only one class

            try:
                import xgboost as xgb
                pos  = int(y_tr.sum())
                neg  = len(y_tr) - pos
                m = xgb.XGBClassifier(
                    n_estimators=100, max_depth=4,
                    scale_pos_weight=round(neg / max(pos, 1), 2),
                    verbosity=0, eval_metric="logloss",
                )
                m.fit(X_tr, y_tr, sample_weight=w_tr, verbose=False)
            except ImportError:
                from sklearn.ensemble import RandomForestClassifier
                m = RandomForestClassifier(
                    n_estimators=100, max_depth=6, class_weight="balanced",
                    n_jobs=-1, random_state=42,
                )
                m.fit(X_tr, y_tr, sample_weight=w_tr)

            preds = m.predict(X_te)
            probs = m.predict_proba(X_te)[:, 1]
            f1s.append(f1_score(y_te, preds, zero_division=0))
            precs.append(precision_score(y_te, preds, zero_division=0))
            recs.append(recall_score(y_te, preds, zero_division=0))
            aucs.append(roc_auc_score(y_te, probs) if len(set(y_te)) > 1 else 0.5)

        if not f1s:
            return {}
        return {
            "f1":        float(np.mean(f1s)),
            "precision": float(np.mean(precs)),
            "recall":    float(np.mean(recs)),
            "auc":       float(np.mean(aucs)),
            "folds":     len(f1s),
        }

    def _predict_proba(self, features: Dict[str, Any],
                       model=None, version: Optional[ModelVersion] = None) -> float:
        """
        Run model inference. Accepts explicit model + version for per-index support.
        Falls back to self._model / self._model_version when not supplied.

        Item 7: checks for feature drift vs training distribution after inference.
        """
        _model   = model   if model   is not None else self._model
        _version = version if version is not None else self._model_version

        cols = (
            _version.feature_cols
            if _version and _version.feature_cols
            else FEATURE_COLUMNS
        )
        row   = np.array([[features.get(c, 0.0) for c in cols]], dtype=np.float32)
        proba = _model.predict_proba(row)[0]
        prob  = float(proba[1]) if len(proba) > 1 else float(proba[0])

        # ── Item 7: Feature drift detection ──────────────────────
        training_stats = (
            _version.training_stats
            if _version and _version.training_stats
            else {}
        )
        if training_stats:
            drifted = []
            for col, (mean, std) in training_stats.items():
                val = features.get(col, 0.0)
                if val == 0.0 or std < 1e-6:
                    continue
                z = abs(val - mean) / std
                if z > 3.5:
                    drifted.append(f"{col}={val:.2f}(z={z:.1f})")
            if drifted:
                logger.debug(
                    f"Feature drift [{getattr(_version, 'model_type', '?')}]: "
                    f"{', '.join(drifted[:5])} — model may be extrapolating"
                )

        return prob

    def _get_top_features(self, features: Dict,
                          version: Optional[ModelVersion] = None,
                          top_n: int = 5) -> Dict[str, float]:
        """Return top N feature contributions for explainability."""
        _version = version if version is not None else self._model_version
        if _version is None:
            return {}
        importance = _version.feature_importance
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
                    version        = meta["version"],
                    trained_at     = datetime.fromisoformat(meta["trained_at"]),
                    samples_used   = meta["samples_used"],
                    model_type     = meta.get("model_type", "Unknown"),
                    metrics        = meta.get("metrics", {}),
                    feature_importance = meta.get("feature_importance", {}),
                    feature_cols   = meta.get("feature_cols", []),
                    training_stats = meta.get("training_stats", {}),
                )
                self._last_sample_count = self._model_version.samples_used
                logger.info(
                    f"Loaded model v{self._model_version.version} "
                    f"({self._model_version.samples_used} samples, "
                    f"{self._model_version.model_type})"
                )
                # Validate that saved feature columns match current FEATURE_COLUMNS.
                # A mismatch means the model was trained with a different engine set
                # and predictions will be silently wrong.
                saved_cols   = set(self._model_version.feature_cols)
                current_cols = set(FEATURE_COLUMNS)
                missing  = current_cols - saved_cols   # new features model doesn't know
                extra    = saved_cols - current_cols   # old features no longer generated
                if missing or extra:
                    logger.warning(
                        f"Feature column mismatch detected in model v{self._model_version.version}! "
                        f"Missing from model: {sorted(missing) or 'none'}. "
                        f"Extra in model (no longer generated): {sorted(extra) or 'none'}. "
                        f"Predictions may be inaccurate — consider retraining."
                    )
                else:
                    logger.info(f"Feature columns validated OK ({len(current_cols)} features match)")
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

    def _get_labeled_count(self, index_name: str = "") -> int:
        try:
            from database.manager import get_db
            if self._db is None:
                self._db = get_db()
            with self._db.get_session() as session:
                from database.models import MLFeatureRecord
                q = session.query(MLFeatureRecord).filter(MLFeatureRecord.label != -1)
                if index_name:
                    q = q.filter(MLFeatureRecord.index_name == index_name)
                return q.count()
        except Exception:
            return 0

    # ─── Per-index model training + persistence (Item 4) ─────────

    def _train_index(self, index_name: str) -> bool:
        """Train a dedicated model for a single index."""
        df = load_dataset(index_name=index_name, labeled_only=True)
        if len(df) < self._MIN_INDEX_SAMPLES:
            return False

        feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        X, y = prepare_features(df)

        sample_weights: Optional[np.ndarray] = None
        if "label_source" in df.columns:
            _sw = {0: 1.0, 1: 3.0, 2: 2.0, 3: 1.5, 4: 1.0}
            sample_weights = np.array(
                [_sw.get(int(s), 1.0) for s in df["label_source"].fillna(0)],
                dtype=np.float32
            )

        model, metrics, importance, training_stats = self._fit_best_model(
            X, y, feature_cols, sample_weights
        )
        if model is None:
            return False

        last_ver = self._index_versions.get(index_name)
        version_num = (last_ver.version + 1) if last_ver else 1
        mv = ModelVersion(
            version        = version_num,
            trained_at     = datetime.now(),
            samples_used   = len(X),
            model_type     = type(model).__name__,
            metrics        = metrics,
            feature_importance = importance,
            feature_cols   = feature_cols,
            training_stats = training_stats,
        )
        with self._lock:
            self._index_models[index_name]        = model
            self._index_versions[index_name]      = mv
            self._index_sample_counts[index_name] = len(X)

        self._save_index_model(index_name, model, mv)
        logger.info(
            f"Model [{index_name}] v{version_num} trained: "
            f"F1={metrics.get('f1', 0):.3f} "
            f"AUC={metrics.get('auc', 0):.3f} "
            f"WF_F1={metrics.get('wf_f1', 0):.3f} "
            f"samples={len(X)}"
        )
        return True

    def _save_index_model(self, index_name: str, model, mv: ModelVersion):
        try:
            tag  = index_name.lower()
            path = MODEL_DIR / f"model_{tag}_v{mv.version}.pkl"
            with open(path, "wb") as f:
                pickle.dump(model, f)
            meta_path = MODEL_DIR / f"model_{tag}_v{mv.version}_meta.json"
            meta_path.write_text(json.dumps(mv.to_dict(), indent=2))
            # Overwrite latest
            with open(MODEL_DIR / f"latest_{tag}.pkl", "wb") as f:
                pickle.dump(model, f)
            (MODEL_DIR / f"latest_{tag}_meta.json").write_text(
                json.dumps(mv.to_dict(), indent=2)
            )
        except Exception as e:
            logger.error(f"Index model save error [{index_name}]: {e}")

    def _load_index_models(self):
        """Load per-index models from disk at startup."""
        for index_name in config.INDICES:
            try:
                tag       = index_name.lower()
                pkl_path  = MODEL_DIR / f"latest_{tag}.pkl"
                meta_path = MODEL_DIR / f"latest_{tag}_meta.json"
                if not pkl_path.exists():
                    continue
                with open(pkl_path, "rb") as f:
                    model = pickle.load(f)
                mv = None
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text())
                    mv = ModelVersion(
                        version        = meta["version"],
                        trained_at     = datetime.fromisoformat(meta["trained_at"]),
                        samples_used   = meta["samples_used"],
                        model_type     = meta.get("model_type", "Unknown"),
                        metrics        = meta.get("metrics", {}),
                        feature_importance = meta.get("feature_importance", {}),
                        feature_cols   = meta.get("feature_cols", []),
                        training_stats = meta.get("training_stats", {}),
                    )
                self._index_models[index_name]   = model
                self._index_versions[index_name] = mv
                self._index_sample_counts[index_name] = mv.samples_used if mv else 0
                logger.info(
                    f"Loaded [{index_name}] model v{mv.version if mv else '?'} "
                    f"({mv.samples_used if mv else '?'} samples)"
                )
            except Exception as e:
                logger.debug(f"Could not load index model [{index_name}]: {e}")


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
