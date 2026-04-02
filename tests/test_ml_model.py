"""tests/test_ml_model.py — ML model smoke tests"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import pytest
import numpy as np


def test_feature_columns_defined():
    from ml.feature_store import FEATURE_COLUMNS
    assert len(FEATURE_COLUMNS) >= 60, f"Only {len(FEATURE_COLUMNS)} features defined"


def test_model_manager_importable():
    from ml.model_manager import get_model_manager
    mm = get_model_manager()
    assert mm is not None


def test_model_version_dataclass():
    from ml.model_manager import ModelVersion
    from datetime import datetime
    mv = ModelVersion(version=1, trained_at=datetime.now(), samples_used=100, model_type="XGB")
    assert mv.version == 1
    assert mv.feature_schema_version >= 1
    assert isinstance(mv.feature_schema_hash, str)


def test_model_prediction_returns_mlprediction():
    from ml.model_manager import get_model_manager, MLPrediction
    mm = get_model_manager()
    # No model loaded in test env — should return a valid MLPrediction
    result = mm.predict({}, direction="BULLISH")
    assert isinstance(result, MLPrediction)


def test_auto_labeler_importable():
    from ml.auto_labeler import AutoLabeler
    al = AutoLabeler()
    assert al is not None
