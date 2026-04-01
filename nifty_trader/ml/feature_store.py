"""
ml/feature_store.py
Machine Learning Integration Layer

Provides utilities for:
  1. Exporting training datasets from SQLite
  2. Proposed model architectures
  3. Model training pipeline stubs (XGBoost, Random Forest, LSTM)
  4. Feature importance analysis

Run standalone:
  python -m ml.feature_store --train --model xgb
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional, Tuple, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# FEATURE ENGINEERING
# ──────────────────────────────────────────────────────────────────

FEATURE_COLUMNS = [
    # Engine 1: Compression
    "compression_ratio", "atr", "atr_pct_change",
    "candle_range_5", "candle_range_20",

    # Engine 2: DI Momentum
    "plus_di", "minus_di", "adx", "di_spread",
    "plus_di_slope", "minus_di_slope",

    # Engine 3: Option Chain
    "pcr", "pcr_change", "call_oi_change", "put_oi_change",
    "iv_rank", "max_pain_distance",

    # Engine 4: Volume Pressure
    "volume_ratio", "volume_ratio_5",

    # Engine 5: Liquidity Trap
    "liq_wick_ratio", "liq_volume_ratio",
    "sweep_up", "sweep_down", "is_small_candle",   # binary trap context

    # Engine 6: Gamma Levels
    "dist_to_gamma_wall", "dist_to_call_wall", "dist_to_put_wall",

    # Engine 7: IV Expansion
    "iv_skew_ratio", "avg_atm_iv", "iv_change_pct",

    # Engine 7-new: VWAP Pressure
    "dist_to_vwap_pct", "vwap_vol_ratio",
    "vwap_cross_up", "vwap_cross_down", "vwap_bounce", "vwap_rejection",

    # Engine 8: Market Regime
    "regime_adx", "regime_atr_ratio",

    # Engine trigger flags (binary)
    "compression_triggered", "di_triggered",
    "option_chain_triggered", "volume_triggered",
    "liquidity_trap_triggered", "gamma_triggered",
    "iv_triggered", "regime_triggered",
    "vwap_triggered",
    "engines_count",

    # Signal timing
    "candle_completion_pct",    # 0.0–1.0: how far into candle when signal fired
                                # Lower = less reliable (incomplete OHLCV); model learns to discount

    # Group A: Time context
    "mins_since_open", "session", "is_expiry", "day_of_week", "dte",

    # Group B: Price context
    "spot_vs_prev_pct", "atr_pct_spot", "chop", "efficiency_ratio", "gap_pct",
    "preopen_gap_pct",   # futures LTP vs prev_close during 9:00–9:14 NSE pre-open, frozen at session start

    # Group C: Candle patterns
    "prev_body_ratio", "prev_bullish", "consec_bull", "consec_bear", "range_expansion",

    # Group D: Index correlation
    "aligned_indices", "market_breadth",

    # Group E: OI & Futures
    "futures_oi_m", "futures_oi_chg_pct", "atm_oi_ratio",
    # Extended futures — institutional footprint (data-only, no gate)
    # basis = futures premium/discount vs spot; regime = price-OI direction analysis
    "excess_basis_pct", "futures_basis_slope",
    "oi_regime", "oi_regime_bullish", "oi_regime_bearish",

    # Group F: MTF ADX + DI slopes
    "adx_5m", "plus_di_5m", "minus_di_5m", "adx_15m",
    # DI angle (slope over last 5 candles on 5m + 15m) — reversal ML learning
    # Negative slope = DI declining = momentum fading on that TF
    "plus_di_slope_5m", "minus_di_slope_5m",
    "plus_di_slope_15m", "minus_di_slope_15m",
    "di_reversal_5m",   # 1 = opposing DI fading on 5m (reversal setup)
    "di_reversal_15m",  # 1 = opposing DI fading on 15m
    "di_reversal_both", # 1 = both TFs show fading opposing DI (strong reversal)

    # Group G: VIX
    "vix", "vix_high",

    # Group G: Price Structure (5m + 15m HH/HL/LH/LL)
    # Collected for ML learning — not used as a gate until ML validates the edge.
    # Encoding: BULLISH=1, NEUTRAL=0, BEARISH=-1
    "struct_5m",           # 5m structure encoded: 1=BULLISH, 0=NEUTRAL, -1=BEARISH
    "struct_15m",          # 15m structure encoded
    "struct_5m_aligned",   # 1 if 5m structure matches signal direction
    "struct_15m_aligned",  # 1 if 15m structure matches signal direction
    "struct_both_aligned", # 1 if both 5m + 15m match signal direction (86% WR in backtest)

    # Group H: Signal identity — direction bias + index bias + signal type
    "direction_encoded",   # 1=BULLISH, -1=BEARISH
    "index_encoded",       # 0=NIFTY, 1=BANKNIFTY, 2=MIDCPNIFTY, 3=SENSEX
    "is_trade_signal",     # 0=EARLY_MOVE, 1=TRADE_SIGNAL

    # Group I: Historical performance context
    "setup_win_rate",          # rolling 20-trade win rate for best-matched setup (0-100)
    "mins_since_last_signal",  # minutes since last TRADE_SIGNAL on same index
]

TARGET_COLUMN = "label"           # 1 = valid move, 0 = false signal
TARGET_DIRECTION = "label_direction"  # 1 = bullish, -1 = bearish, 0 = no move
TARGET_QUALITY = "label_quality"      # 0=SL_hit, 1=T1_hit, 2=T2_hit, 3=T3_hit (graded win quality)


def load_dataset(
    index_name: Optional[str] = None,
    labeled_only: bool = True
) -> pd.DataFrame:
    """Load ML feature records from SQLite."""
    from database.manager import get_db
    db = get_db()
    records = db.get_ml_dataset(index_name, labeled_only)

    if not records:
        logger.warning("No ML records found")
        return pd.DataFrame(columns=FEATURE_COLUMNS + [TARGET_COLUMN])

    # records is already a list of plain dicts (get_ml_dataset converts inside session)
    df = pd.DataFrame(records)
    return df


def prepare_features(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Extract X, y arrays from dataframe."""
    feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[feature_cols].fillna(0).values.astype(np.float32)
    y = df[TARGET_COLUMN].values.astype(np.int32)
    return X, y


# ──────────────────────────────────────────────────────────────────
# MODEL: XGBOOST (recommended for first iteration)
# ──────────────────────────────────────────────────────────────────

class XGBSignalClassifier:
    """
    XGBoost binary classifier.
    Predicts: will this early alert lead to a real price move? (1/0)

    Install: pip install xgboost
    """

    def __init__(self):
        self.model = None
        self._feature_names = FEATURE_COLUMNS

    def train(self, df: pd.DataFrame, test_size: float = 0.2):
        try:
            import xgboost as xgb  # type: ignore
            from sklearn.model_selection import train_test_split  # type: ignore
            from sklearn.metrics import classification_report  # type: ignore
        except ImportError:
            logger.error("Install: pip install xgboost scikit-learn")
            return

        X, y = prepare_features(df)
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=test_size, random_state=42)

        self.model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
        )
        self.model.fit(
            X_tr, y_tr,
            eval_set=[(X_te, y_te)],
            verbose=False,
        )
        preds = self.model.predict(X_te)
        logger.info(f"\n{classification_report(y_te, preds)}")
        return self

    def predict_proba(self, features: Dict) -> float:
        """Returns probability that this alert is a valid move."""
        if self.model is None:
            return 0.5
        row = [[features.get(c, 0) for c in self._feature_names]]
        return float(self.model.predict_proba(row)[0][1])

    def save(self, path: str = "models/xgb_signal.json"):
        if self.model:
            import os; os.makedirs("models", exist_ok=True)
            self.model.save_model(path)

    def load(self, path: str = "models/xgb_signal.json"):
        try:
            import xgboost as xgb  # type: ignore
            self.model = xgb.XGBClassifier()
            self.model.load_model(path)
        except Exception as e:
            logger.error(f"Model load failed: {e}")


# ──────────────────────────────────────────────────────────────────
# MODEL: RANDOM FOREST
# ──────────────────────────────────────────────────────────────────

class RFSignalClassifier:
    """
    Random Forest — good baseline, interpretable via feature importance.
    Install: pip install scikit-learn
    """

    def __init__(self):
        self.model = None

    def train(self, df: pd.DataFrame):
        try:
            from sklearn.ensemble import RandomForestClassifier  # type: ignore
            from sklearn.model_selection import train_test_split, cross_val_score  # type: ignore
        except ImportError:
            logger.error("Install: pip install scikit-learn")
            return

        X, y = prepare_features(df)
        self.model = RandomForestClassifier(
            n_estimators=300, max_depth=6,
            min_samples_leaf=5, n_jobs=-1, random_state=42
        )
        scores = cross_val_score(self.model, X, y, cv=5, scoring="f1")
        self.model.fit(X, y)
        logger.info(f"RF CV F1: {scores.mean():.3f} ± {scores.std():.3f}")
        return self

    def feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}
        importances = self.model.feature_importances_
        return dict(sorted(
            zip(FEATURE_COLUMNS, importances),
            key=lambda x: x[1], reverse=True
        ))


# ──────────────────────────────────────────────────────────────────
# MODEL: LSTM  (for sequential pattern recognition)
# ──────────────────────────────────────────────────────────────────

class LSTMSignalPredictor:
    """
    LSTM for learning multi-step temporal patterns.
    Best for capturing "compression → breakout" sequences over time.

    Install: pip install tensorflow  OR  pip install torch
    Sequence length: 10 candles of features → predict move
    """

    def __init__(self, seq_len: int = 10):
        self.seq_len = seq_len
        self.model   = None

    def build_sequences(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Convert flat records into (samples, timesteps, features)."""
        feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        X_flat = df[feature_cols].fillna(0).values
        y_flat = df[TARGET_COLUMN].values

        X_seq, y_seq = [], []
        for i in range(self.seq_len, len(X_flat)):
            X_seq.append(X_flat[i - self.seq_len:i])
            y_seq.append(y_flat[i])
        return np.array(X_seq, dtype=np.float32), np.array(y_seq, dtype=np.int32)

    def build_keras_model(self, n_features: int):
        try:
            from tensorflow import keras  # type: ignore
            model = keras.Sequential([
                keras.layers.LSTM(64, return_sequences=True,
                                   input_shape=(self.seq_len, n_features)),
                keras.layers.Dropout(0.2),
                keras.layers.LSTM(32),
                keras.layers.Dropout(0.2),
                keras.layers.Dense(16, activation="relu"),
                keras.layers.Dense(1, activation="sigmoid"),
            ])
            model.compile(optimizer="adam", loss="binary_crossentropy",
                          metrics=["accuracy"])
            return model
        except ImportError:
            logger.error("Install TensorFlow: pip install tensorflow")
            return None

    def train(self, df: pd.DataFrame, epochs: int = 50):
        X, y = self.build_sequences(df)
        if len(X) == 0:
            logger.warning("Not enough sequential data for LSTM")
            return
        model = self.build_keras_model(X.shape[2])
        if model:
            model.fit(X, y, epochs=epochs, batch_size=32,
                      validation_split=0.2, verbose=1)
            self.model = model


# ──────────────────────────────────────────────────────────────────
# ML INTEGRATION NOTES
# ──────────────────────────────────────────────────────────────────
"""
FUTURE ML PIPELINE:

1. Data Collection (auto — already built in)
   Every alert auto-saves to ml_feature_store table.
   Label outcomes manually: alert.is_valid = True/False

2. Labeling Strategy
   - Price moved 1× ATR in predicted direction within 5 candles → label=1
   - Price didn't move or reversed → label=0
   - Can be automated with post-market price comparison

3. Training Schedule
   - Weekly retraining recommended
   - Minimum 500 labeled samples for XGBoost
   - Minimum 2000 for LSTM

4. Model Integration
   - Load model in SignalAggregator._run_evaluation()
   - Multiply base confidence by ML probability
   - Raise MIN_ENGINES_FOR_ALERT to 2 if ML confidence > 0.8

5. Recommended First Model
   XGBoost → quickest to train, most interpretable
   Feature importance reveals which engine matters most

6. Evaluation Metrics
   - Precision (of alerts that fired, how many were correct?)
   - Recall (how many real moves were captured?)
   - F1 for balance
   - Sharpe ratio on simulated PnL
"""
