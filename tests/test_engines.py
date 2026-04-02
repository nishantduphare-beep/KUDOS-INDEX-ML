"""tests/test_engines.py — Engine smoke tests"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import pytest


def test_compression_engine_importable():
    from engines.compression import CompressionDetector
    engine = CompressionDetector()
    assert engine is not None


def test_di_momentum_engine_importable():
    from engines.di_momentum import DIMomentumDetector
    engine = DIMomentumDetector()
    assert engine is not None


def test_iv_expansion_engine_importable():
    from engines.iv_expansion import IVExpansionDetector
    engine = IVExpansionDetector()
    assert engine is not None


def test_vwap_pressure_engine_importable():
    from engines.vwap_pressure import VWAPPressureDetector
    engine = VWAPPressureDetector()
    assert engine is not None


def test_signal_aggregator_importable():
    from engines.signal_aggregator import SignalAggregator
    agg = SignalAggregator()
    assert agg is not None
