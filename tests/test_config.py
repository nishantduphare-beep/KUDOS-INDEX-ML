"""tests/test_config.py — Config validation tests"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import pytest
import config


def test_broker_valid():
    valid = {"fyers", "dhan", "kite", "upstox", "mock"}
    assert config.BROKER in valid, f"BROKER={config.BROKER} not in {valid}"


def test_min_engines_in_range():
    assert 1 <= config.MIN_ENGINES_FOR_SIGNAL <= 8


def test_ml_confidence_threshold_sane():
    # ML_SIGNAL_GATE_THRESHOLD is the actual config attribute name
    assert 0.3 <= config.ML_SIGNAL_GATE_THRESHOLD <= 0.95


def test_candle_interval_standard():
    assert config.CANDLE_INTERVAL_MINUTES in {1, 3, 5, 10, 15, 30}


def test_vix_thresholds_exist():
    # Direction-aware VIX thresholds added in v3.3
    assert hasattr(config, "MAX_VIX_FOR_BULLISH_SIGNAL")
    assert hasattr(config, "MAX_VIX_FOR_BEARISH_SIGNAL")
    assert config.MAX_VIX_FOR_BULLISH_SIGNAL < config.MAX_VIX_FOR_BEARISH_SIGNAL
