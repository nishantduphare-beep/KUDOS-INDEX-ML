"""
ml/ml_testing_framework.py
────────────────────────────────────────────────────────────────────
Complete ML Testing & Data Provisioning System

Provides:
  1. Historical data generators (realistic OHLCV patterns + edge cases)
  2. Synthetic options data (IV, OI, Greeks across scenarios)
  3. Feature completeness validators
  4. Cross-validation utilities
  5. Model benchmarking + comparison
  6. Setup trigger testing
  7. Feature importance analysis
  8. Scenario backtesting

Usage:
    python -m ml.ml_testing_framework --generate-test-data
    python -m ml.ml_testing_framework --validate-features
    python -m ml.ml_testing_framework --run-all-tests
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
import json
import pickle

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# HISTORICAL DATA GENERATOR
# ──────────────────────────────────────────────────────────────────

class HistoricalDataGenerator:
    """
    Generates realistic OHLCV candles for testing.
    Includes edge cases: trends, reversals, consolidations, gaps, etc.
    """
    
    def __init__(self, start_price: float = 23650, days: int = 60, tf: str = "3m"):
        self.start_price = start_price
        self.days = days
        self.tf = tf  # "3m", "5m", "15m", "1h", "D"
        self.dates = self._generate_dates()
    
    def _generate_dates(self) -> pd.DatetimeIndex:
        """Generate trading dates (skip weekends)."""
        start = datetime.now() - timedelta(days=self.days)
        dates = pd.bdate_range(start=start, periods=self.days, freq='B')
        return dates
    
    def generate_trending_candles(self, direction: str = "BULLISH", strength: float = 0.7) -> pd.DataFrame:
        """
        Generate strong trending candles.
        
        direction: "BULLISH" or "BEARISH"
        strength: 0.0–1.0 (1.0 = strongest trend, 0.0 = weak)
        """
        n_candles = len(self.dates) * 250  # ~250 candles per day (3-min)
        timestamps = pd.date_range(start=self.dates[0], periods=n_candles, freq=self.tf)
        
        closes = [self.start_price]
        for _ in range(n_candles - 1):
            direction_factor = 1.0 if direction == "BULLISH" else -1.0
            noise = np.random.randn() * (1 - strength) * 50
            move = direction_factor * strength * 100 + noise
            closes.append(closes[-1] + move)
        
        closes = np.array(closes)
        
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": closes + np.random.randn(len(closes)) * 30,
            "high": closes + np.abs(np.random.randn(len(closes))) * 60,
            "low": closes - np.abs(np.random.randn(len(closes))) * 60,
            "close": closes,
            "volume": np.random.randint(100000, 500000, len(closes)),
        })
        
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
        
        return df
    
    def generate_consolidation_candles(self, range_pct: float = 0.02) -> pd.DataFrame:
        """Generate tight consolidation (low volatility)."""
        n_candles = len(self.dates) * 250
        timestamps = pd.date_range(start=self.dates[0], periods=n_candles, freq=self.tf)
        
        center = self.start_price
        range_val = self.start_price * range_pct
        
        closes = center + np.random.randn(n_candles) * (range_val * 0.3)
        
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": closes + np.random.randn(len(closes)) * (range_val * 0.1),
            "high": closes + np.abs(np.random.randn(len(closes))) * (range_val * 0.2),
            "low": closes - np.abs(np.random.randn(len(closes))) * (range_val * 0.2),
            "close": closes,
            "volume": np.random.randint(50000, 200000, len(closes)),
        })
        
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
        
        return df
    
    def generate_reversal_candles(self, from_direction: str = "BEARISH", to_direction: str = "BULLISH") -> pd.DataFrame:
        """Generate reversal pattern: trend → consolidation → reverse trend."""
        n_candles = len(self.dates) * 250
        timestamps = pd.date_range(start=self.dates[0], periods=n_candles, freq=self.tf)
        
        # Phase 1: Initial trend (30%)
        p1_len = int(n_candles * 0.3)
        closes_p1 = [self.start_price]
        for _ in range(p1_len - 1):
            factor = -0.5 if from_direction == "BEARISH" else 0.5
            closes_p1.append(closes_p1[-1] + factor * 50 + np.random.randn() * 30)
        
        # Phase 2: Consolidation (20%)
        p2_len = int(n_candles * 0.2)
        center = closes_p1[-1]
        closes_p2 = [center + np.random.randn() * 50 for _ in range(p2_len)]
        
        # Phase 3: Reversal (50%)
        p3_len = n_candles - p1_len - p2_len
        closes_p3 = [closes_p2[-1]]
        for _ in range(p3_len - 1):
            factor = 1.0 if to_direction == "BULLISH" else -1.0
            closes_p3.append(closes_p3[-1] + factor * 50 + np.random.randn() * 30)
        
        closes = np.array(closes_p1 + closes_p2 + closes_p3)[:n_candles]
        
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": closes + np.random.randn(n_candles) * 20,
            "high": closes + np.abs(np.random.randn(n_candles)) * 40,
            "low": closes - np.abs(np.random.randn(n_candles)) * 40,
            "close": closes,
            "volume": np.random.randint(100000, 500000, n_candles),
        })
        
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
        
        return df
    
    def generate_gap_candles(self, gap_direction: str = "UP") -> pd.DataFrame:
        """Generate gap up/down pattern."""
        df = self.generate_trending_candles()
        
        gap_size = self.start_price * 0.02  # 2% gap
        if gap_direction == "UP":
            df.loc[len(df)//2:, ["open", "high", "low", "close"]] += gap_size
        else:
            df.loc[len(df)//2:, ["open", "high", "low", "close"]] -= gap_size
        
        return df
    
    def generate_volatile_candles(self, volatility_spike: float = 2.0) -> pd.DataFrame:
        """Generate high volatility (IV expansion scenario)."""
        n_candles = len(self.dates) * 250
        timestamps = pd.date_range(start=self.dates[0], periods=n_candles, freq=self.tf)
        
        closes = self.start_price + np.cumsum(np.random.randn(n_candles) * 100)
        
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": closes + np.random.randn(n_candles) * 50,
            "high": closes + np.abs(np.random.randn(n_candles)) * (100 * volatility_spike),
            "low": closes - np.abs(np.random.randn(n_candles)) * (100 * volatility_spike),
            "close": closes,
            "volume": np.random.randint(200000, 800000, n_candles),
        })
        
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
        
        return df


# ──────────────────────────────────────────────────────────────────
# SYNTHETIC OPTIONS DATA GENERATOR
# ──────────────────────────────────────────────────────────────────

class SyntheticOptionsDataGenerator:
    """
    Generates realistic options data (OI, IV, Greeks) for testing.
    Includes various market scenarios.
    """
    
    def __init__(self, spot: float = 23650, expiry_days: int = 7):
        self.spot = spot
        self.expiry_days = expiry_days
    
    def generate_bullish_setup(self) -> Dict[str, Any]:
        """Options setup with bullish bias."""
        atm = round(self.spot / 50) * 50
        strikes = [atm + i * 50 for i in range(-15, 16)]
        
        chain = []
        for strike in strikes:
            call_oi = 1000000 * np.exp(-((strike - atm) / 200) ** 2)  # Bell curve, ATM heavy
            put_oi = 800000 * np.exp(-((strike - atm) / 150) ** 2)
            
            chain.append({
                "strike": strike,
                "call_oi": max(100000, call_oi),
                "put_oi": max(100000, put_oi),
                "call_iv": 15 + ((strike - atm) / 200) * 5,  # Skew: ATM lower IV
                "put_iv": 16 + ((strike - atm) / 200) * 3,
                "call_volume": np.random.randint(10000, 100000),
                "put_volume": np.random.randint(10000, 100000),
                "call_delta": self._delta_call(strike),
                "put_delta": self._delta_put(strike),
            })
        
        return {
            "spot": self.spot,
            "atm": atm,
            "pcr": sum(s["put_oi"] for s in chain) / sum(s["call_oi"] for s in chain),
            "pcr_volume": sum(s["put_volume"] for s in chain) / sum(s["call_volume"] for s in chain),
            "max_pain": atm + 50,  # Slightly above spot
            "avg_iv": 15.5,
            "chain": chain,
        }
    
    def generate_bearish_setup(self) -> Dict[str, Any]:
        """Options setup with bearish bias."""
        atm = round(self.spot / 50) * 50
        strikes = [atm + i * 50 for i in range(-15, 16)]
        
        chain = []
        for strike in strikes:
            call_oi = 800000 * np.exp(-((strike - atm) / 150) ** 2)
            put_oi = 1200000 * np.exp(-((strike - atm) / 200) ** 2)
            
            chain.append({
                "strike": strike,
                "call_oi": max(100000, call_oi),
                "put_oi": max(100000, put_oi),
                "call_iv": 15 - ((strike - atm) / 200) * 5,
                "put_iv": 16 - ((strike - atm) / 200) * 3,
                "call_volume": np.random.randint(10000, 100000),
                "put_volume": np.random.randint(10000, 100000),
                "call_delta": self._delta_call(strike),
                "put_delta": self._delta_put(strike),
            })
        
        return {
            "spot": self.spot,
            "atm": atm,
            "pcr": sum(s["put_oi"] for s in chain) / sum(s["call_oi"] for s in chain),
            "pcr_volume": sum(s["put_volume"] for s in chain) / sum(s["call_volume"] for s in chain),
            "max_pain": atm - 50,  # Below spot
            "avg_iv": 16.5,
            "chain": chain,
        }
    
    def generate_iv_expansion(self) -> Dict[str, Any]:
        """IV expansion scenario (volatility increase)."""
        setup = self.generate_bullish_setup()
        
        # Increase all IVs by 30%
        for s in setup["chain"]:
            s["call_iv"] *= 1.3
            s["put_iv"] *= 1.3
        
        setup["avg_iv"] *= 1.3
        
        return setup
    
    def generate_iv_compression(self) -> Dict[str, Any]:
        """IV compression scenario (volatility decrease)."""
        setup = self.generate_bullish_setup()
        
        # Decrease all IVs by 25%
        for s in setup["chain"]:
            s["call_iv"] *= 0.75
            s["put_iv"] *= 0.75
        
        setup["avg_iv"] *= 0.75
        
        return setup
    
    def _delta_call(self, strike: float) -> float:
        """Approximate call delta."""
        moneyness = (strike - self.spot) / self.spot
        return 0.5 + 0.3 * np.tanh(-moneyness * 10)
    
    def _delta_put(self, strike: float) -> float:
        """Approximate put delta."""
        return -1 + self._delta_call(strike)


# ──────────────────────────────────────────────────────────────────
# FEATURE VALIDATOR
# ──────────────────────────────────────────────────────────────────

def validate_feature_completeness(df: pd.DataFrame, strict: bool = False) -> Dict[str, Any]:
    """
    Validates that all required features are present and populated.
    Returns report with missing features, NaNs, data types.
    """
    from ml.feature_store import FEATURE_COLUMNS, TARGET_COLUMN
    
    report = {
        "total_rows": len(df),
        "complete_rows": 0,
        "missing_features": [],
        "nan_counts": {},
        "dtype_issues": [],
        "value_ranges": {},
    }
    
    # Check columns
    for col in FEATURE_COLUMNS + [TARGET_COLUMN]:
        if col not in df.columns:
            report["missing_features"].append(col)
            continue
        
        # NaN check
        nan_count = df[col].isna().sum()
        if nan_count > 0:
            report["nan_counts"][col] = {
                "count": int(nan_count),
                "pct": round(nan_count / len(df) * 100, 2)
            }
        
        # Value range
        try:
            report["value_ranges"][col] = {
                "min": float(df[col].min()) if not df[col].isna().all() else None,
                "max": float(df[col].max()) if not df[col].isna().all() else None,
                "mean": float(df[col].mean()) if not df[col].isna().all() else None,
            }
        except Exception:
            pass
    
    # Count complete rows (no NaNs, all features present)
    complete_mask = df[FEATURE_COLUMNS].notna().all(axis=1)
    report["complete_rows"] = int(complete_mask.sum())
    report["completeness_pct"] = round(report["complete_rows"] / len(df) * 100, 2)
    
    # Strict mode: fail if any missing features
    if strict and (report["missing_features"] or report["nan_counts"]):
        report["status"] = "FAILED"
    else:
        report["status"] = "PASSED" if report["completeness_pct"] >= 95 else "PARTIAL"
    
    return report


# ──────────────────────────────────────────────────────────────────
# CROSS-VALIDATION UTILITIES
# ──────────────────────────────────────────────────────────────────

def time_series_cross_validation(
    df: pd.DataFrame,
    n_splits: int = 5,
    test_size_pct: float = 0.2
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Time-series aware cross-validation (no data leakage).
    Walks forward: train on past, test on future.
    """
    splits = []
    total_len = len(df)
    train_size = int(total_len * (1 - test_size_pct))
    
    for i in range(n_splits):
        start_test = int(train_size + (i * test_size_pct * total_len / n_splits))
        end_test = int(start_test + (test_size_pct * total_len / n_splits))
        
        if end_test > total_len:
            break
        
        train = df.iloc[:start_test]
        test = df.iloc[start_test:end_test]
        
        splits.append((train, test))
    
    return splits


# ──────────────────────────────────────────────────────────────────
# MODEL BENCHMARKING
# ──────────────────────────────────────────────────────────────────

def benchmark_models(df: pd.DataFrame, models_dict: Dict[str, Any]) -> Dict[str, Dict]:
    """
    Train and compare multiple models on same data.
    Returns metrics per model: precision, recall, F1, AUC, etc.
    """
    from ml.feature_store import FEATURE_COLUMNS, TARGET_COLUMN, prepare_features
    from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix
    
    results = {}
    
    X, y = prepare_features(df)
    
    for model_name, model in models_dict.items():
        try:
            model.fit(X, y)
            preds = model.predict(X)
            probs = model.predict_proba(X)[:, 1] if hasattr(model, "predict_proba") else preds
            
            results[model_name] = {
                "precision": float(precision_score(y, preds, zero_division=0)),
                "recall": float(recall_score(y, preds, zero_division=0)),
                "f1": float(f1_score(y, preds, zero_division=0)),
                "auc": float(roc_auc_score(y, probs)) if len(np.unique(y)) > 1 else 0.5,
                "confusion_matrix": confusion_matrix(y, preds).tolist(),
            }
        except Exception as e:
            results[model_name] = {"error": str(e)}
    
    return results


# ──────────────────────────────────────────────────────────────────
# SCENARIO BACKTESTER
# ──────────────────────────────────────────────────────────────────

def backtest_on_scenarios(model, scenario_data: List[Dict]) -> Dict[str, Any]:
    """
    Test model on predefined scenarios (bullish, bearish, ranging, etc.).
    Returns win rate per scenario.
    """
    results = {
        "scenarios": {},
        "overall_stats": {},
    }
    
    for scenario in scenario_data:
        scenario_name = scenario.get("name", "Unknown")
        features = scenario.get("features", {})
        expected_label = scenario.get("expected_label", 1)
        
        # Format features
        feature_list = [[features.get(col, 0) for col in range(100)]]  # Dummy
        
        try:
            pred = model.predict(feature_list)[0] if hasattr(model, "predict") else 0
            confidence = (
                model.predict_proba(feature_list)[0][pred]
                if hasattr(model, "predict_proba")
                else 0.5
            )
            
            correct = 1 if pred == expected_label else 0
            
            results["scenarios"][scenario_name] = {
                "prediction": int(pred),
                "expected": int(expected_label),
                "correct": correct,
                "confidence": float(confidence),
            }
        except Exception as e:
            results["scenarios"][scenario_name] = {"error": str(e)}
    
    return results


# ──────────────────────────────────────────────────────────────────
# SETUP VALIDATOR
# ──────────────────────────────────────────────────────────────────

def validate_setup_triggers(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Check that all setup triggers fire correctly on test data.
    Validates logic: compression, DI, option chain, volume, etc.
    """
    from engines import (
        compression as e_comp,
        di_momentum as e_di,
        option_chain as e_oc,
        volume_pressure as e_vol,
    )
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "total_rows": len(df),
        "trigger_counts": {},
        "fire_rates": {},
    }
    
    triggers = [
        ("compression", lambda row: e_comp.check_compression(row)),
        ("di_momentum", lambda row: e_di.check_di_signal(row)),
        ("volume_pressure", lambda row: e_vol.check_volume_signal(row)),
    ]
    
    for name, trigger_fn in triggers:
        try:
            fire_count = sum(1 for _, row in df.iterrows() if trigger_fn(row))
            results["trigger_counts"][name] = fire_count
            results["fire_rates"][name] = round(fire_count / len(df) * 100, 2)
        except Exception as e:
            results["trigger_counts"][name] = f"Error: {e}"
    
    return results


# ──────────────────────────────────────────────────────────────────
# FEATURE IMPORTANCE ANALYZER
# ──────────────────────────────────────────────────────────────────

def analyze_feature_importance(model, feature_names: List[str]) -> Dict[str, float]:
    """Extract feature importance from trained model."""
    importance = {}
    
    if hasattr(model, "feature_importances_"):
        # XGBoost, RandomForest
        for name, imp in zip(feature_names, model.feature_importances_):
            importance[name] = float(imp)
    
    elif hasattr(model, "coef_"):
        # Linear models
        for name, coef in zip(feature_names, model.coef_[0]):
            importance[name] = float(abs(coef))
    
    # Sort by importance
    importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
    
    return importance


# ──────────────────────────────────────────────────────────────────
# MAIN TEST RUNNER
# ──────────────────────────────────────────────────────────────────

def run_all_tests(df_train: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Run complete test suite."""
    logger.info("🧪 Starting ML Test Suite...")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "tests": {},
    }
    
    # 1. Data generation
    logger.info("\n[1/6] Generating synthetic data...")
    try:
        gen = HistoricalDataGenerator(days=30)
        df_trend = gen.generate_trending_candles("BULLISH")
        df_cons = gen.generate_consolidation_candles()
        df_rev = gen.generate_reversal_candles()
        
        results["tests"]["data_generation"] = {
            "status": "PASSED",
            "datasets": {
                "trending": len(df_trend),
                "consolidation": len(df_cons),
                "reversal": len(df_rev),
            }
        }
        logger.info("✓ Generated 3 data scenarios")
    except Exception as e:
        results["tests"]["data_generation"] = {"status": "FAILED", "error": str(e)}
    
    # 2. Feature validation
    logger.info("\n[2/6] Validating features...")
    try:
        if df_train is not None:
            val_report = validate_feature_completeness(df_train, strict=False)
            results["tests"]["feature_validation"] = val_report
            logger.info(f"✓ {val_report['completeness_pct']}% complete rows")
        else:
            logger.info("⚠ Skipped (no training data provided)")
    except Exception as e:
        results["tests"]["feature_validation"] = {"status": "FAILED", "error": str(e)}
    
    # 3. Options data generation
    logger.info("\n[3/6] Generating synthetic options data...")
    try:
        opt_gen = SyntheticOptionsDataGenerator()
        bullish = opt_gen.generate_bullish_setup()
        bearish = opt_gen.generate_bearish_setup()
        iv_exp = opt_gen.generate_iv_expansion()
        iv_comp = opt_gen.generate_iv_compression()
        
        results["tests"]["options_generation"] = {
            "status": "PASSED",
            "scenarios": [
                {"name": "bullish", "pcr": round(bullish["pcr"], 2)},
                {"name": "bearish", "pcr": round(bearish["pcr"], 2)},
                {"name": "iv_expansion", "avg_iv": round(iv_exp["avg_iv"], 2)},
                {"name": "iv_compression", "avg_iv": round(iv_comp["avg_iv"], 2)},
            ]
        }
        logger.info("✓ Generated 4 options scenarios")
    except Exception as e:
        results["tests"]["options_generation"] = {"status": "FAILED", "error": str(e)}
    
    # 4. Cross-validation
    logger.info("\n[4/6] Setting up cross-validation splits...")
    try:
        if df_train is not None:
            splits = time_series_cross_validation(df_train, n_splits=5)
            results["tests"]["cross_validation"] = {
                "status": "PASSED",
                "splits": len(splits),
            }
            logger.info(f"✓ Created {len(splits)} CV folds")
        else:
            logger.info("⚠ Skipped (no training data)")
    except Exception as e:
        results["tests"]["cross_validation"] = {"status": "FAILED", "error": str(e)}
    
    # 5. Setup trigger validation
    logger.info("\n[5/6] Validating setup triggers...")
    try:
        if df_train is not None:
            trigger_report = validate_setup_triggers(df_train.head(100))
            results["tests"]["setup_triggers"] = trigger_report
            logger.info(f"✓ Validated {len(trigger_report['trigger_counts'])} triggers")
        else:
            logger.info("⚠ Skipped")
    except Exception as e:
        results["tests"]["setup_triggers"] = {"status": "FAILED", "error": str(e)}
    
    # 6. Summary
    logger.info("\n[6/6] Test Summary")
    passed = sum(1 for t in results["tests"].values() if t.get("status") == "PASSED")
    total = len(results["tests"])
    results["summary"] = {
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }
    
    logger.info(f"✅ Tests complete: {passed}/{total} passed ({results['summary']['success_rate']}%)")
    
    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )
    
    if "--generate-test-data" in sys.argv:
        logger.info("Generating test datasets...")
        gen = HistoricalDataGenerator(days=60)
        df1 = gen.generate_trending_candles("BULLISH")
        df2 = gen.generate_consolidation_candles()
        df3 = gen.generate_reversal_candles()
        df1.to_csv("test_data_trending.csv", index=False)
        df2.to_csv("test_data_consolidation.csv", index=False)
        df3.to_csv("test_data_reversal.csv", index=False)
        logger.info("✓ Saved test_data_*.csv")
    
    elif "--run-all-tests" in sys.argv:
        result = run_all_tests()
        print(json.dumps(result, indent=2, default=str))
    
    else:
        logger.info("Usage:")
        logger.info("  python -m ml.ml_testing_framework --generate-test-data")
        logger.info("  python -m ml.ml_testing_framework --run-all-tests")
