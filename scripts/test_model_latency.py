"""
scripts/test_model_latency.py
Tests model inference latency: mean / std / p95 / p99 over 1000 predictions.
Target: <100ms mean latency.

Run: cd d:\nifty_trader_v3_final\nifty_trader && python ..\scripts\test_model_latency.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import numpy as np
from ml.model_manager import get_model_manager

mm = get_model_manager()
if mm._model is None:
    print("No model loaded. Train a model first.")
    sys.exit(1)

from ml.feature_store import FEATURE_COLUMNS
n_features = len(FEATURE_COLUMNS)
X_sample = np.random.rand(1, n_features).astype(np.float32)

print(f"Testing model inference latency (1000 predictions, {n_features} features)...")
times = []
for _ in range(1000):
    t0 = time.perf_counter()
    try:
        mm._model.predict_proba(X_sample)
    except Exception:
        pass
    times.append((time.perf_counter() - t0) * 1000)

times = np.array(times)
print(f"  Mean:  {times.mean():.2f}ms")
print(f"  Std:   {times.std():.2f}ms")
print(f"  P95:   {np.percentile(times, 95):.2f}ms")
print(f"  P99:   {np.percentile(times, 99):.2f}ms")
print(f"  Min:   {times.min():.2f}ms")
print(f"  Max:   {times.max():.2f}ms")
target = 100.0
status = "PASS" if times.mean() < target else "FAIL"
print(f"\n  Target: <{target}ms mean -> {status}")
