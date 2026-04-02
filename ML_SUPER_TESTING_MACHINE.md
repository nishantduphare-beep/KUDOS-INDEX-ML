# 🧠 ML SUPER TESTING MACHINE - Complete Guide

## Overview

ML system ko full power mode mein convert karne ke liye comprehensive testing framework:

✅ **Historical Data Generation** — All market scenarios (trends, reversals, gaps, volatility)  
✅ **Synthetic Options Data** — Bullish, bearish, IV expansion, IV compression  
✅ **Feature Validation** — Verify all 111 features complete & correct  
✅ **Model Training** — Cross-validation, benchmarking, scenario testing  
✅ **Trigger Analysis** — Which setups actually work  
✅ **Sensitivity Testing** — How model responds to market changes  
✅ **Automated Reporting** — Performance metrics per scenario  

---

## Quick Start

### 1. Generate Test Data

```bash
cd d:\nifty_trader_v3_final

# Generate synthetic OHLCV candles (all scenarios)
python -m ml.ml_testing_framework --generate-test-data

# This creates:
#   test_data_trending.csv (bullish/bearish trends)
#   test_data_consolidation.csv (low volatility range)
#   test_data_reversal.csv (trend reversal + breakout)
```

### 2. Run Complete ML Tests

```bash
# Full diagnostic suite (all tests)
python -m ml.ml_super_tester --full-test

# Output:
#   ml_test_report_YYYYMMDD_HHMMSS.json
#   Contains: feature validation, trigger analysis, model metrics, scenarios
```

### 3. Load Real Data + Test

```python
from ml.ml_super_tester import MLSuperTester
from database.manager import get_db

# Initialize with real DB
db = get_db()
tester = MLSuperTester(db)

# Run full suite
report = tester.run_full_test()

# Check which triggers win most
triggers = report['tests']['trigger_analysis']['trigger_win_rates']
for trigger, stats in triggers.items():
    print(f"{trigger}: {stats['win_rate']}% WR on {stats['fire_count']} setups")
```

---

## Modules Reference

### 1. `ml_testing_framework.py` — Test Data Generator

**What it generates:**

#### A. Historical Data (OHLCV)

```python
from ml.ml_testing_framework import HistoricalDataGenerator

gen = HistoricalDataGenerator(start_price=23650, days=60, tf="3m")

# Trending market
df_bullish = gen.generate_trending_candles(direction="BULLISH", strength=0.8)
df_bearish = gen.generate_trending_candles(direction="BEARISH", strength=0.8)

# Consolidation (low vol)
df_cons = gen.generate_consolidation_candles(range_pct=0.02)

# Reversal pattern (reversal setups)
df_rev = gen.generate_reversal_candles(from_direction="BEARISH", to_direction="BULLISH")

# Gaps
df_gap_up = gen.generate_gap_candles(gap_direction="UP")
df_gap_down = gen.generate_gap_candles(gap_direction="DOWN")

# Volatility spike (IV expansion)
df_volatile = gen.generate_volatile_candles(volatility_spike=2.0)
```

**Output:** Realistic 3-min candles for 60 days with:
- Open, High, Low, Close, Volume
- Random walk + directional bias
- Edge cases for testing

---

#### B. Synthetic Options Data

```python
from ml.ml_testing_framework import SyntheticOptionsDataGenerator

opt_gen = SyntheticOptionsDataGenerator(spot=23650, expiry_days=7)

# Bullish setup (more call OI, lower ATM IV)
bullish = opt_gen.generate_bullish_setup()
print(bullish["pcr"])           # Put-Call Ratio (< 1.0 = bullish)
print(bullish["chain"])          # All 31 strikes with OI, IV, Greeks

# Bearish setup (more put OI)
bearish = opt_gen.generate_bearish_setup()
print(bearish["pcr"])           # > 1.0 (bearish)

# IV Expansion (vol spike)
iv_exp = opt_gen.generate_iv_expansion()
print(iv_exp["avg_iv"])         # 30% higher

# IV Compression (vol drop)
iv_comp = opt_gen.generate_iv_compression()
print(iv_comp["avg_iv"])        # 25% lower
```

**Output:** Complete options chain with:
- Strike prices (ATM ± 15 × 50)
- OI, Volume, IV
- Call + Put Greeks (delta, gamma, theta, vega)
- PCR, Max Pain, IV Rank

---

### 2. `ml_super_tester.py` — Main Test Orchestrator

**Complete Testing Pipeline:**

```python
from ml.ml_super_tester import MLSuperTester

tester = MLSuperTester()  # Auto-connects to DB

# 1. Load Data
report = tester.run_full_test()

# 2. Check Feature Validation
features = report['tests']['feature_validation']
print(f"Coverage: {features['overall']['coverage_pct']}%")
print(f"Missing: {features['overall']['data_quality']['nan_pct']}% NaN")

# 3. Trigger Analysis
triggers = report['tests']['trigger_analysis']
for trigger, stats in triggers['trigger_win_rates'].items():
    print(f"\n{trigger}:")
    print(f"  Fire Rate: {stats['fire_rate_pct']}%")
    print(f"  Win Rate: {stats['win_rate']}%")

# 4. Model Performance
model = report['tests']['model_training']
print(f"\nModel Metrics:")
print(f"  Train F1: {model['model_metrics']['train']['f1']}")
print(f"  Test F1: {model['model_metrics']['test']['f1']}")
print(f"  AUC: {model['model_metrics']['test']['auc']}")

# 5. Top Features by Importance
print(f"\nTop Features:")
for feat, imp in list(model['top_features'].items())[:10]:
    print(f"  {feat}: {imp:.4f}")

# 6. Scenario Performance
scenarios = report['tests']['scenarios']
for scenario, stats in scenarios.items():
    print(f"\n{scenario}: {stats['stats']['win_rate']:.1f}% WR ({stats['records']} setups)")
```

---

## Complete Testing Workflow

### Phase 1: Data Generation

```bash
# Generate all market condition data
python -c "
from ml.ml_testing_framework import HistoricalDataGenerator
gen = HistoricalDataGenerator(days=90)

# 6 different market conditions
conditions = [
    ('trending_bull.csv', gen.generate_trending_candles('BULLISH')),
    ('trending_bear.csv', gen.generate_trending_candles('BEARISH')),
    ('consolidation.csv', gen.generate_consolidation_candles()),
    ('reversal.csv', gen.generate_reversal_candles()),
    ('gap_up.csv', gen.generate_gap_candles('UP')),
    ('volatile.csv', gen.generate_volatile_candles(2.0)),
]

for name, df in conditions:
    df.to_csv(f'test_data/{name}', index=False)
    print(f'✓ Generated {name} ({len(df)} rows)')
"
```

### Phase 2: Feature Engineering Validation

```python
from ml.ml_super_tester import FeatureEngineValidator
from ml.feature_store import load_dataset

# Load real training data
df = load_dataset(labeled_only=True)

# Validate
validator = FeatureEngineValidator()
report = validator.validate_all_features(df)

print("Feature Groups Coverage:")
for group, stats in report['validation'].items():
    print(f"  {group}: {stats['coverage_pct']}% ({stats['present']}/{stats['present']+stats['missing']})")

print(f"\nOverall: {report['overall']['coverage_pct']}% ({report['overall']['features_present']}/111)")
```

### Phase 3: Trigger Effectiveness

```python
from ml.ml_super_tester import TriggerAnalyzer

analyzer = TriggerAnalyzer()
analysis = analyzer.analyze_trigger_correlation(df)

print("Trigger Win Rates (sorted):")
for trigger, stats in analysis['trigger_win_rates'].items():
    print(f"  {trigger}:")
    print(f"    Fire: {stats['fire_rate_pct']}%")
    print(f"    Win Rate: {stats['win_rate']}%")
    print(f"    Profit Factor: {stats['win_rate'] / (100-stats['win_rate']) if stats['win_rate'] != 100 else 'infinity'}")
```

### Phase 4: Model Training & Validation

```python
from ml.ml_super_tester import MLModelTrainer
from sklearn.model_selection import train_test_split

# Split data
df_train, df_test = train_test_split(df, test_size=0.2, random_state=42)

# Train
trainer = MLModelTrainer()
result = trainer.train_and_validate(df_train, df_test)

print("\nModel Performance:")
print(f"Train Set:")
for metric, value in result['model_metrics']['train'].items():
    print(f"  {metric}: {value:.3f}")

print(f"\nTest Set:")
for metric, value in result['model_metrics']['test'].items():
    print(f"  {metric}: {value:.3f}")

print(f"\nTop 15 Features:")
for feat, imp in result['top_features'].items():
    print(f"  {feat}: {imp:.4f}")
```

### Phase 5: Scenario Testing

```python
from ml.ml_super_tester import ScenarioTester

tester = ScenarioTester()
scenarios = tester.test_all_scenarios(df)

print("\nPerformance by Market Condition:")
for scenario, stats in scenarios.items():
    print(f"  {scenario}:")
    print(f"    Setups: {stats['records']}")
    print(f"    Win Rate: {stats['stats']['win_rate']}%")
```

---

## Advanced: Custom Testing

### Test Specific Setup Type

```python
# Find all compression setups that worked
compression_wins = df[
    (df['compression_triggered'] == 1) &
    (df['label'] == 1)
]

print(f"Compression Setup Statistics:")
print(f"  Total fires: {df[df['compression_triggered']==1].shape[0]}")
print(f"  Wins: {len(compression_wins)}")
print(f"  Win rate: {len(compression_wins) / df[df['compression_triggered']==1].shape[0] * 100:.1f}%")

# Analyze winning vs losing setups
print(f"\nTop features in winning setups:")
winning_features = compression_wins[FEATURE_COLUMNS].mean()
print(winning_features.nlargest(10))
```

### Cross-Validation on Time-Series

```python
from ml.ml_testing_framework import time_series_cross_validation

splits = time_series_cross_validation(df, n_splits=5, test_size_pct=0.2)

for i, (train, test) in enumerate(splits):
    print(f"\nSplit {i+1}:")
    print(f"  Train: {len(train)} rows ({train['timestamp'].min()} → {train['timestamp'].max()})")
    print(f"  Test: {len(test)} rows ({test['timestamp'].min()} → {test['timestamp'].max()})")
    
    # Train model on this split
    trainer = MLModelTrainer()
    result = trainer.train_and_validate(train, test)
    print(f"  Test F1: {result['model_metrics']['test']['f1']:.3f}")
```

### Model Comparison

```python
from ml.ml_testing_framework import benchmark_models
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier

models = {
    'XGBoost': xgb.XGBClassifier(n_estimators=200, max_depth=5),
    'RandomForest': RandomForestClassifier(n_estimators=200, max_depth=6),
}

results = benchmark_models(df, models)

print("Model Comparison:")
for model_name, metrics in results.items():
    print(f"\n{model_name}:")
    for metric, value in metrics.items():
        print(f"  {metric}: {value:.3f}")
```

---

## Performance Targets

### Feature Completeness

```
✅ Target: 95%+ complete rows
✅ NaN Tolerance: <5% per feature
✅ Features Present: 110/111+ (99%)
```

### Trigger Effectiveness

```
Trigger                    Win Rate Target
─────────────────────────────────────
compression                 65%+
di_momentum                 62%+
volume_pressure             60%+
liquidity_trap              68%+
gamma_levels                58%+
iv_expansion                61%+
regime                      60%+
vwap_pressure               59%+
```

### Model Performance

```
Data Split       F1 Target    Precision    Recall    AUC
────────────────────────────────────────────────────────
Train            75%+         75%+         70%+      80%+
Validation       72%+         73%+         68%+      78%+
Test             70%+         70%+         65%+      75%+
```

### Scenario Coverage

```
Scenario                 Expected Cases    Win Rate Target
──────────────────────────────────────────────────────────
Bullish Trends           20%               72%+
Bearish Trends           18%               68%+
High Volatility          15%               65%+
Low Volatility           12%               58%+
Expiry Day               10%               55%+
Early Session            15%               62%+
Closing Session          10%               68%+
```

---

## Troubleshooting

### "No data in DB"

```python
# Generate synthetic instead
from ml.ml_testing_framework import HistoricalDataGenerator
gen = HistoricalDataGenerator(days=90)
df = gen.generate_trending_candles()

# Or load from CSV
import pandas as pd
df = pd.read_csv("test_data_trending.csv")
```

### "Features missing/incomplete"

```python
# Check what's missing
from ml.ml_super_tester import FeatureEngineValidator
validator = FeatureEngineValidator()
report = validator.validate_all_features(df)

# Fill missing features with 0
from ml.feature_store import FEATURE_COLUMNS
for col in FEATURE_COLUMNS:
    if col not in df.columns:
        df[col] = 0.0
```

### "Model not improving"

1. Check feature importance:
   ```python
   from ml.ml_testing_framework import analyze_feature_importance
   imp = analyze_feature_importance(model, FEATURE_COLUMNS)
   print(imp)  # If all ~equal, features might not be informative
   ```

2. Check class imbalance:
   ```python
   print(df['label'].value_counts())  # Should be 50:50 ideally, not 90:10
   ```

3. Check triggers firing frequently:
   ```python
   triggers = ['compression_triggered', 'di_triggered', 'volume_triggered']
   for t in triggers:
       fire_rate = df[t].sum() / len(df) * 100
       print(f"{t}: {fire_rate:.1f}%")  # Should be 15-30%, not 0% or 100%
   ```

---

## Files Generated by Tests

```
.
├── test_data/
│   ├── trending_bull.csv
│   ├── trending_bear.csv
│   ├── consolidation.csv
│   ├── reversal.csv
│   ├── gap_up.csv
│   └── volatile.csv
│
├── ml_test_reports/
│   ├── ml_test_report_20260402_153614.json
│   └── cross_validation_results.json
│
└── logs/
    ├── ml_testing_framework.log
    └── ml_super_tester.log
```

---

## Commands Reference

```bash
# Generate test data
python -m ml.ml_testing_framework --generate-test-data

# Run all tests
python -m ml.ml_super_tester --full-test

# Manual feature validation
python -c "
from ml.ml_super_tester import FeatureEngineValidator
from ml.feature_store import load_dataset
df = load_dataset(labeled_only=True)
validator = FeatureEngineValidator()
report = validator.validate_all_features(df)
print(report)
"

# Export test report
python -c "
from ml.ml_super_tester import MLSuperTester
tester = MLSuperTester()
report = tester.run_full_test()
import json
with open('ml_diagnostics.json', 'w') as f:
    json.dump(report, f, indent=2, default=str)
print('✓ Report saved')
"
```

---

## Summary

**ML ko Super Thinking Machine banane ke liye:**

1. ✅ Generate synthetic data for all scenarios
2. ✅ Validate all 111 features complete
3. ✅ Analyze which triggers actually work
4. ✅ Train models with proper cross-validation
5. ✅ Test on specific market scenarios
6. ✅ Extract feature importance
7. ✅ Compare model architectures
8. ✅ Auto-generate performance reports

**Sab tools available hain - ab sirf run karo! 🚀**

```bash
python -m ml.ml_super_tester --full-test
```

This will run complete diagnostics + tell you exactly where ML system stands.
