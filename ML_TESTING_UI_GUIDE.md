# 🧠 ML SUPER TESTER - UI TAB GUIDE

## 🚀 Where to Find It

**UI Tab Name:** `🧠  ML TESTER`

Located in the main NiftyTrader UI (8th tab)

```
[Credentials] [Dashboard] [Scanner] [Options Flow] [Alerts] [HQ Trades] [Setups] [Ledger] [S11] [👈 ML TESTER]
```

---

## 📋 Quick Start Commands (Available in UI)

### 1. FULL ML DIAGNOSTIC (15-30 min)
**Button:** `▶  RUN FULL TEST`

Runs complete ML testing suite:
- ✅ Load real & synthetic data
- ✅ Validate all 111 features
- ✅ Analyze 9 trigger win rates
- ✅ Train XGBoost model
- ✅ Test 9 market scenarios
- ✅ Auto-generate JSON report

**Output:** `logs/ml_test_report_YYYYMMDD_HHMMSS.json`

---

### 2. GENERATE SYNTHETIC DATA (2-5 min)
**Button:** `📊  GENERATE TEST DATA`

Creates realistic test data for 6 market scenarios:
- Trending Bullish (with strength)
- Trending Bearish (with strength)
- Consolidation (low volatility)
- Reversals (breakout patterns)
- Gap patterns (up/down)
- Volatile (IV expansion 2x)

**Output:** `test_data/` directory with 6 CSV files (60 days each, 3-min candles)

---

### 3. EXPORT OPTIONS DATA (1-3 min)
**Button:** `📤  EXPORT OPTIONS DATA`

Manual trigger for daily options export:
- EOD Prices CSV (11K+ rows)
- Snapshots CSV (1.5K rows)
- ML Features CSV (pre-computed)
- Summary JSON (metadata)

**Output:** `logs/options_data_exports/` with 4 files

---

### 4. VALIDATE FEATURES (2-5 min)
**Button:** `✓  VALIDATE FEATURES`

Tests all 111 features in real training data:
- ✅ Check feature presence
- ✅ Detect NaN/missing values
- ✅ Analyze value ranges
- ✅ Generate data quality report

**Output:** Results displayed in table + JSON report

---

## 📊 UI Tabs

### Tab 1: ⚡ QUICK START
- 4 command buttons
- Feature descriptions
- Example metric displays

### Tab 2: 📊 RESULTS
- Results table (METRIC | VALUE)
- "Open Last Report" button
- JSON viewer

### Tab 3: 📝 LOG
- Real-time progress bar
- Timestamped log messages
- Auto-scroll to latest message

---

## 🔄 How It Works

### Multi-threaded Architecture
```
UI Button Click
    ↓
Launch MLTestWorker (background thread)
    ↓
Run test (doesn't block UI)
    ↓
Emit progress signals → Log display
    ↓
Emit results → Results table
    ↓
Test complete ✅
```

### Progress Signals
```
Progress Message → Log display with timestamp
Test Complete → Results table + JSON export
Error → Error log + retry available
```

---

## 📁 Files & Locations

### Code
```
nifty_trader/ui/ml_testing_tab.py      (400+ lines)
nifty_trader/ui/main_window.py         (updated)
```

### Generated Reports
```
logs/ml_test_report_YYYYMMDD_HHMMSS.json
logs/options_data_exports/
  ├─ options_eod_YYYY-MM-DD.csv
  ├─ options_snapshots_YYYY-MM-DD.csv
  ├─ options_ml_features_YYYY-MM-DD.csv
  └─ export_summary_YYYY-MM-DD.json
```

### Test Data
```
test_data/
  ├─ test_data_trending_bullish.csv
  ├─ test_data_trending_bearish.csv
  ├─ test_data_consolidation.csv
  ├─ test_data_reversal.csv
  ├─ test_data_gap_up.csv
  └─ test_data_volatile.csv
```

---

## ✨ Features

✅ **Non-blocking UI** - Long tests run in background thread
✅ **Real-time Progress** - Updates every step
✅ **Error Handling** - Graceful error messages
✅ **Button States** - Auto-disable during test, enable after
✅ **Report Viewer** - Opens JSON reports directly
✅ **Timestamped Logs** - Track execution timeline
✅ **Multi-threaded Worker** - 4 test types supported

---

## 🎯 Test Matrix

| Test | Time | Data | Output |
|------|------|------|--------|
| Full Diagnostic | 15-30 min | Real + Synthetic | JSON report |
| Gen Test Data | 2-5 min | Synthetic | 6 CSV files |
| Export Options | 1-3 min | Real DB | 4 export files |
| Validate Features | 2-5 min | Real DB | Feature report |

---

## 🚀 Running from Terminal (Alternative)

```bash
# Via Python module
python -m ml.ml_super_tester --full-test

# Via CLI script
python export_options_data.py

# Generate data programmatically
python -c "
from ml.ml_testing_framework import HistoricalDataGenerator
gen = HistoricalDataGenerator(days=90)
df = gen.generate_trending_candles('BULLISH')
df.to_csv('test.csv', index=False)
"
```

---

## 📊 Example Results Output

### Full Diagnostic Report
```json
{
  "timestamp": "2026-04-02T15:30:45.123456",
  "tests": {
    "data_loading": {
      "real_data_rows": 1250,
      "synthetic_data_rows": 2500,
      "status": "success"
    },
    "feature_validation": {
      "total_features": 111,
      "present": 111,
      "coverage_pct": 100,
      "complete_rows": 95.2
    },
    "trigger_analysis": {
      "compression_triggered": {
        "fire_rate": 12.5,
        "win_rate": 65.3,
        "fire_count": 187
      },
      "di_triggered": {
        "fire_rate": 8.3,
        "win_rate": 62.1,
        "fire_count": 124
      }
      ...
    },
    "model_metrics": {
      "train": {
        "accuracy": 0.68,
        "f1": 0.65,
        "auc": 0.72
      },
      "test": {
        "accuracy": 0.62,
        "f1": 0.58,
        "auc": 0.65
      }
    },
    "scenario_results": {
      "bullish_trend": {
        "records": 312,
        "win_rate": 68.2
      },
      "bearish_trend": {
        "records": 298,
        "win_rate": 64.1
      }
      ...
    },
    "top_features": [
      "atm_iv",
      "iv_percentile",
      "pcr",
      ...
    ]
  }
}
```

---

## 🔧 Troubleshooting

### Test Hangs
- Check log tab for progress messages
- May take time for first run (data loading)
- Cancel and retry if stuck 5+ min

### No Data Found
- Run from main.py first (initializes DB)
- Check if credentials are valid
- Run "Generate Test Data" instead

### Feature Validation Fails
- Ensure main.py ran and collected data
- Check if 30+ days of market data exists
- Otherwise use synthetic data

### JSON Report Not Found
- Reports saved to `logs/ml_test_report_*.json`
- Check if logs directory exists
- May need to run at least one test first

---

## ✅ Status

**Status:** PRODUCTION READY ✅
**UI Integration:** Complete ✅
**Multi-threading:** Implemented ✅
**GitHub:** Pushed ✅

---

## 📝 Next Steps

1. Start NiftyTrader.bat or run main.py
2. Navigate to "🧠 ML TESTER" tab
3. Click one of the 4 buttons:
   - Full Test (comprehensive)
   - Generate Data (synthetic)
   - Export Options (daily data)
   - Validate Features (quality check)
4. Monitor progress in Log tab
5. View results in Results tab
6. Click "Open Last Report" to see JSON

**Iss sab kuch ab UI par available hai!** 🚀
