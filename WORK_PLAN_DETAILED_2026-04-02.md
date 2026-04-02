# 📋 **NIFTYTRADER v3 - DETAILED WORK PLAN**

**Created:** April 2, 2026  
**Status:** 🔴 PENDING APPROVAL  
**Total Estimated Time:** 15-18 hours  
**Phases:** 4 (Database → Broker → ML → Testing)

---

## **PHASE 1: DATABASE RECOVERY** (90 minutes)

### Task 1.1: Backup Current Database
- **What:** Create backup of niftytrader.db before any changes
- **How:** Copy to niftytrader.db.backup-2026-04-02
- **Why:** Rollback capability if something breaks
- **Time:** 5 min
- **Risk:** Low
- **Effort:** Trivial

### Task 1.2: Delete Empty Database File
- **What:** Remove corrupted niftytrader.db (0 tables)
- **How:** Delete d:\nifty_trader_v3_final\niftytrader.db
- **Why:** Fresh slate for schema creation
- **Time:** 2 min
- **Risk:** Very Low (backed up)
- **Effort:** Trivial

### Task 1.3: Initialize SQLAlchemy Schema
- **What:** Run DatabaseManager to create 9 tables
- **How:** 
  ```python
  from nifty_trader.database.manager import get_db
  db = get_db()
  ```
- **Why:** Creates Base.metadata.create_all()
- **Time:** 5 min
- **Risk:** Low
- **Effort:** Trivial
- **Expected Output:** niftytrader.db with 9 tables, all indices

### Task 1.4: Run All Migrations
- **What:** Apply _migrate_* methods to add all columns
- **How:**
  ```python
  db._migrate_ml_feature_store()
  db._migrate_ml_feature_outcomes()
  db._migrate_trade_outcomes()
  db._migrate_alerts()
  db._migrate_option_eod_prices()
  db._migrate_indexes()
  db._migrate_setup_alerts()
  db._migrate_s11_paper_trades()
  db._migrate_auto_paper_trades()
  db._migrate_option_chain_snapshots()
  db._migrate_market_candles()
  ```
- **Why:** Ensure all columns exist (100+ columns across tables)
- **Time:** 10 min
- **Risk:** Low (idempotent)
- **Effort:** Medium
- **Expected Output:** All migrations logged in stdout

### Task 1.5: Validate Schema Completeness
- **What:** Verify all 9 tables exist with correct row counts
- **How:** Run diagnostic.py after Phase 1.4
- **Why:** Confirm no silent migration failures
- **Time:** 5 min
- **Risk:** Low
- **Effort:** Trivial
- **Expected Output:**
  ```
  ✓ market_candles: 0 rows
  ✓ alerts: 0 rows
  ✓ ml_feature_store: 0 rows
  ✓ option_chain_snapshots: 0 rows
  ... (9 total)
  ```

### Task 1.6: Set Database Pragmas
- **What:** Configure SQLite performance settings
- **How:** Execute in PRAGMA commands in manager.py startup:
  ```sql
  PRAGMA journal_mode=WAL;        -- Write-ahead logging
  PRAGMA busy_timeout=30000;      -- 30s timeout
  PRAGMA foreign_keys=ON;         -- Referential integrity
  PRAGMA synchronous=NORMAL;      -- Balance safety/speed
  ```
- **Why:** Optimize for concurrent reads + single writer
- **Time:** 2 min
- **Risk:** Low
- **Effort:** Trivial
- **Expected Output:** SQLite optimized for trading workload

### Task 1.7: Create Auto-Backup Script
- **What:** Add daily checkpoint + backup mechanism
- **How:** Create scheduler in main.py:
  ```python
  def schedule_daily_backup():
      # At 15:35 IST (post-market), checkpoint WAL
      # Copy db to backups/niftytrader_YYYY-MM-DD.db
  ```
- **Why:** Prevent data loss from crashes/corruption
- **Time:** 10 min
- **Risk:** Very Low (background task)
- **Effort:** Low
- **Expected Output:** Daily backups in backups/ folder

---

## **PHASE 2: BROKER INTEGRATION & AUTHENTICATION** (150 minutes)

### Task 2.1: Check Fyers Token Status
- **What:** Verify current token validity
- **How:** Read auth/fyers_token.json, check expires_at
- **Why:** Token expired Mar 20, needs refresh
- **Time:** 2 min
- **Risk:** Very Low (read-only)
- **Effort:** Trivial
- **Expected Output:** Token expired confirmation

### Task 2.2: Implement Token Auto-Refresh
- **What:** Add automatic token refresh before expiry
- **How:** Modify fyers_adapter.py:
  ```python
  def _check_token_expiry_on_startup():
      token = load_fyers_token()
      exp = datetime.fromisoformat(token['expires_at'])
      if (exp - datetime.now()).total_seconds() < 3600:  # < 1h left
          logger.warning("Token expiring soon, prompt user to refresh")
          raise TokenExpiryWarning()
  ```
- **Why:** Prevent mid-session token expiry → API failures
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Clear "Token expires in 30 min" warning

### Task 2.3: Add Broker Connection Health Check
- **What:** Implement health_check() method in CombinedBrokerAdapter
- **How:**
  ```python
  def health_check() -> Dict[str, Any]:
      return {
          'connected': self._connected,
          'last_tick_age_sec': (time.time() - self._last_tick_ts),
          'spot_price': self._spot_cache.get('NIFTY'),
          'option_chain_fresh': (time.time() - self._oc_ts) < 15,
      }
  ```
- **Why:** Detect stale data / broker disconnections
- **Time:** 20 min
- **Risk:** Low
- **Effort:** Medium
- **Expected Output:** Health endpoint callable from UI + monitoring

### Task 2.4: Test Fyers Spot API (Mock)
- **What:** Verify get_spot_price() works without auth
- **How:** Call with mock data, verify response structure
- **Why:** Catch API format changes before live
- **Time:** 10 min
- **Risk:** Very Low (mock-only)
- **Effort:** Trivial
- **Expected Output:** Mock spot prices returning correctly

### Task 2.5: Test Fyers Option Chain API (Mock)
- **What:** Verify get_option_chain() structure
- **How:** Call with mock data, check PCR/OI/IV fields
- **Why:** Ensure feature extraction works
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Mock option chain complete

### Task 2.6: Implement Broker Rate-Limit Handler
- **What:** Add retry logic for 429 (Too Many Requests) errors
- **How:** Backoff strategy in fyers_adapter.py:
  ```python
  def _handle_rate_limit(attempt: int) -> float:
      # 1s, 4s, 9s, 16s exponential backoff
      return (attempt ** 2)
  ```
- **Why:** Prevent API ban from bursts
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Rate-limit resilience

### Task 2.7: Create Broker Connection Test Suite
- **What:** Automated tests for all 5 broker adapters
- **How:** 
  ```python
  def test_fyers_spot_price():
  def test_fyers_option_chain():
  def test_fyers_auth_url():
  ... (15 more tests)
  ```
- **Why:** Catch regressions before deployment
- **Time:** 30 min
- **Risk:** Very Low
- **Effort:** Medium
- **Expected Output:** 20 passing unit tests

### Task 2.8: Setup Paper Trading Mode
- **What:** Ensure paper_trading flag properly gates order placement
- **How:** Verify OrderManager checks paper_trading=True before Fyers calls
- **Why:** Prevent accidental live trades during testing
- **Time:** 15 min
- **Risk:** CRITICAL (safety)
- **Effort:** Medium
- **Expected Output:** Paper orders tracked in S11PaperTrade table, NOT placed on Fyers

### Task 2.9: Document Broker Setup Guide
- **What:** Create step-by-step OAuth setup instructions
- **How:** Document in BROKER_SETUP.md:
  ```
  1. Start app → Credentials tab
  2. Select "Fyers"
  3. Click "Generate Auth URL"
  4. Copy link to browser
  5. Login with mobile number
  6. Allow permissions
  7. Copy auth code back to app
  ```
- **Why:** Users need clear instructions
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Markdown guide + screenshots

### Task 2.10: Add Connection Retry Logic to DataManager
- **What:** Auto-reconnect broker if connection drops
- **How:** Background thread in DataManager.run():
  ```python
  while True:
      if not broker.is_connected():
          logger.warning("Broker disconnected, reconnecting...")
          broker.connect()
          time.sleep(5)
      time.sleep(30)
  ```
- **Why:** Graceful handling of network blips
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Auto-reconnect within 30s of disconnect

---

## **PHASE 3: ML MODEL FIXES & RETRAINING** (240 minutes)

### Task 3.1: Audit AutoLabeler Labeling Logic
- **What:** Review auto_labeler.py to find why 92% labels are negative
- **How:** Trace label generation in OutcomeTracker:
  ```python
  # Check: are all TRUE trades being labeled as -1 (unlabeled)?
  # Check: SL hit = label 0, but are SLs hitting too much?
  # Check: are label_source weights being applied?
  ```
- **Why:** Root cause of model poisoning
- **Time:** 30 min
- **Risk:** Medium (code review intensive)
- **Effort:** High
- **Expected Output:** Issue identified + fix plan

### Task 3.2: Fix Label Source Weighting
- **What:** Ensure higher-quality labels (TradeOutcome) have weight=3.0
- **How:** Modify ml/model_manager.py training pipeline:
  ```python
  sample_weights = np.array([
      _source_weight.get(int(s), 1.0) 
      for s in df['label_source'].fillna(0)
  ])
  # Pass to model.fit(X, y, sample_weight=sample_weights)
  ```
- **Why:** Weak ATR heuristics shouldn't dominate training
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Sample weights properly applied in training

### Task 3.3: Implement Class Balancing
- **What:** Use SMOTE or class_weight to handle 92% negative imbalance
- **How:** 
  ```python
  from sklearn.utils.class_weight import compute_class_weight
  class_weights = compute_class_weight('balanced', classes=[0,1], y=y)
  model.fit(X, y, class_weight={0: class_weights[0], 1: class_weights[1]})
  ```
- **Why:** Prevent model from predicting all 0s
- **Time:** 20 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Balanced class weighting in v29 model

### Task 3.4: Validate Feature Completeness
- **What:** Ensure all 79 FEATURE_COLUMNS exist in ml_feature_store
- **How:** Query sample feature record, check for NaN/missing columns
  ```python
  sample = db.get_ml_dataset(index_name='NIFTY', labeled_only=False)[0]
  missing = [c for c in FEATURE_COLUMNS if c not in sample or pd.isna(sample[c])]
  ```
- **Why:** Feature mismatch will crash inference
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** All 79 features populated, NaN < 5%

### Task 3.5: Add Feature Schema Versioning
- **What:** Store feature_schema_version in model metadata
- **How:** Add to ModelVersion dataclass:
  ```python
  feature_schema_version: int  # Increment if FEATURE_COLUMNS changes
  feature_schema_hash: str     # SHA256 of FEATURE_COLUMNS list
  ```
- **Why:** Catch feature order mismatches at load time
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Schema version stored in all future models

### Task 3.6: Fix Feature Extraction in Signal Aggregator
- **What:** Verify all 79 features are populated in _build_ml_features()
- **How:** Add debug logging for missing features:
  ```python
  expected_features = set(FEATURE_COLUMNS)
  actual_features = set(features_dict.keys())
  missing = expected_features - actual_features
  if missing:
      logger.warning(f"Missing features: {missing}")
  ```
- **Why:** Ensure no silent feature loss
- **Time:** 20 min
- **Risk:** Medium
- **Effort:** Medium
- **Expected Output:** Debug log shows exact features populated

### Task 3.7: Retrain Model v29 (Clean Data)
- **What:** Train new model on re-labeled + class-balanced data
- **How:** Run training pipeline:
  ```bash
  python -m nifty_trader.ml.model_manager --retrain --force
  ```
- **Why:** Replace v28 (poisoned) with v29 (clean)
- **Time:** 45 min (includes training + validation)
- **Risk:** Medium (depends on data quality)
- **Effort:** High (iterative tuning)
- **Expected Output:** 
  ```
  Model v29 trained:
  F1=0.72, Precision=0.68, Recall=0.77, AUC=0.81
  Samples=4337, Pos=400, Neg=3069
  feature_schema_version=2
  ```

### Task 3.8: Hyperparameter Tuning
- **What:** Optimize XGBoost/RF hyperparameters for best F1
- **How:** Grid search over key params:
  ```python
  param_grid = {
      'max_depth': [5, 7, 10],
      'learning_rate': [0.01, 0.05, 0.1],
      'n_estimators': [100, 200, 300],
  }
  best_params = grid_search(X_train, y_train, param_grid)
  ```
- **Why:** Maximize predictive power
- **Time:** 60 min
- **Risk:** Low (cross-validated)
- **Effort:** High
- **Expected Output:** Best hyperparameters stored; F1 +5-10%

### Task 3.9: Cross-Validation Testing
- **What:** Evaluate model on held-out time series data
- **How:** Time-series K-fold split (not random):
  ```python
  # Train on Mar 19-25, test on Mar 26-31
  # Train on Mar 26-31, test on Apr 1
  # Average metrics across folds
  ```
- **Why:** Detect overfitting + ensure forward-looking generalization
- **Time:** 30 min
- **Risk:** Low
- **Effort:** Medium
- **Expected Output:** Cross-validation metrics stable across folds

### Task 3.10: Feature Importance Analysis
- **What:** Identify top 10 most predictive features
- **How:** Extract feature_importance from trained model
- **Why:** Understand what drives predictions; plan future engineering
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** 
  ```
  Top 10 Features:
  1. pcr (0.137)
  2. iv_skew_ratio (0.097)
  3. minus_di_5m (0.069)
  ...
  ```

### Task 3.11: Drop Zero-Importance Features
- **What:** Remove iv_rank, iv_change_pct, vix, futures_oi_* (0.0 importance)
- **How:** Remove from FEATURE_COLUMNS, re-train v30
- **Why:** Faster training, cleaner feature set
- **Time:** 15 min
- **Risk:** Low (these features don't help anyway)
- **Effort:** Low
- **Expected Output:** FEATURE_COLUMNS reduced from 79 to 73

### Task 3.12: Implement Model Checkpointing (Best Model)
- **What:** Save separate "best_model_v{N}" checkpoint when F1 improves
- **How:** After each retrain:
  ```python
  if new_f1 > best_f1_on_file:
      save_model(model, f'best_model_v{N}_f1_{new_f1:.3f}')
  ```
- **Why:** Quick rollback to previous best if model degrades
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** best_model_vX_f1_0.XXX.pkl tracking

---

## **PHASE 4: CODE IMPROVEMENTS & TESTING** (180 minutes)

### Task 4.1: Add Comprehensive Error Handling
- **What:** Wrap all critical code paths with try-except + logging
- **Where:**
  - `DataManager.start()` → catch broker exceptions
  - `SignalAggregator._scan()` → catch engine evaluation timeouts
  - `ml/model_manager.py` → catch model load/predict failures
  - `database/manager.py` → catch migration + query failures
- **How:**
  ```python
  try:
      result = broker.get_spot_price()
  except BrokerAPIError as e:
      logger.error(f"Broker API failed: {e}; returning cached price")
      result = self._spot_cache.get('NIFTY')
  ```
- **Why:** Graceful degradation instead of crashes
- **Time:** 45 min
- **Risk:** Low
- **Effort:** Medium
- **Expected Output:** All critical code paths logged + recovered

### Task 4.2: Add Data Validation
- **What:** Validate all incoming data (spot, option chain, candles)
- **How:**
  ```python
  def validate_candle(candle):
      assert candle['close'] > 0, "Close price must be positive"
      assert candle['high'] >= candle['low'], "High must be >= Low"
      assert candle['volume'] >= 0, "Volume cannot be negative"
  ```
- **Why:** Catch corrupt data before it reaches ML
- **Time:** 20 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Data validation in DataManager + feature store

### Task 4.3: Implement Graceful Shutdown
- **What:** Cleanly close resources on app exit
- **How:** Add atexit handlers:
  ```python
  def on_exit():
      logger.info("Graceful shutdown initiated")
      data_manager.stop()
      db.close()  # Checkpoint WAL
      logger.info("All resources closed")
  atexit.register(on_exit)
  ```
- **Why:** Prevent data loss on app crashes
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Clean shutdown logs

### Task 4.4: Add Configuration Validation
- **What:** Verify all config settings on startup
- **How:**
  ```python
  def validate_config():
      assert BROKER in ['fyers', 'dhan', 'kite', 'mock']
      assert 0 < MIN_ENGINES_FOR_SIGNAL <= 6
      assert 0 < VOLUME_SPIKE_MULTIPLIER < 5.0
  ```
- **Why:** Catch config mistakes before they cause issues
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** Config validation at startup

### Task 4.5: Implement Comprehensive Logging
- **What:** Add structured logging with levels + modules
- **How:** Already have basic logging, enhance with:
  - Separate files per module (engine logs, ml logs, broker logs)
  - Log rotation (daily + size-based)
  - Metrics dashboard (alert count, model predictions/day)
- **Time:** 30 min
- **Risk:** Very Low
- **Effort:** Low
- **Expected Output:** logs/niftytrader_YYYYMMDD.log + module-specific logs

### Task 4.6: Add Unit Tests (20 Critical Tests)
- **Where:** tests/test_*.py
- **Coverage:**
  - test_database.py (5 tests)
  - test_broker_adapters.py (5 tests)
  - test_engines.py (5 tests)
  - test_ml_model.py (5 tests)
- **How:** Use pytest + mock
- **Why:** Catch regressions before deployment
- **Time:** 60 min
- **Risk:** Low
- **Effort:** High
- **Expected Output:** 20 passing tests with >80% code coverage on critical paths

### Task 4.7: Performance Profiling
- **What:** Identify bottlenecks (DataManager, SignalAggregator, ML inference)
- **How:** Use cProfile:
  ```python
  python -m cProfile -s cumtime main.py
  ```
- **Why:** Ensure <100ms latency end-to-end
- **Time:** 20 min
- **Risk:** Very Low
- **Effort:** Low
- **Expected Output:** 
  ```
  bottleneck 1: signal_aggregator._scan() = 45ms
  bottleneck 2: ml model.predict() = 38ms
  bottleneck 3: db queries = 12ms
  ```

### Task 4.8: Add Monitoring Dashboard Stub
- **What:** Create simple status UI tab showing:
  - Broker connection status + last tick age
  - Model status (F1 score, samples trained)
  - Alert counts (today, this week, this month)
  - P&L tracker (Today's realized PnL from closed trades)
- **How:** Add `MonitoringTab` to ui/main_window.py
- **Time:** 45 min
- **Risk:** Low
- **Effort:** Medium
- **Expected Output:** Real-time dashboard accessible from UI

### Task 4.9: Documentation Updates
- **What:** Update all docs to reflect fixes
- **Where:**
  - DOCUMENTATION.md (update ML architecture + schema)
  - BROKER_SETUP.md (new; OAuth guide)
  - MODEL_VERSIONING.md (new; model management)
  - TROUBLESHOOTING.md (FAQ + common errors)
- **Time:** 45 min
- **Risk:** Very Low
- **Effort:** Low
- **Expected Output:** 4 comprehensive markdown files

### Task 4.10: Code Quality Pass
- **What:** Run linters + formatters
- **How:**
  ```bash
  black nifty_trader/ --line-length=100
  pylint nifty_trader/ --disable=all --enable=E,F
  ```
- **Why:** Consistent readable code
- **Time:** 15 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Formatted code, no lint errors

---

## **PHASE 5: INTEGRATION TESTING** (120 minutes)

### Task 5.1: Mock Broker 24-Hour Simulation
- **What:** Run entire app with mock broker for 24h clock (simulated)
- **How:** Modify DataManager to use mock clock, compress 24h into 10 min
- **Why:** Catch threading bugs, signal quality issues
- **Time:** 30 min setup + 10 min run
- **Risk:** Medium
- **Effort:** Medium
- **Expected Output:** 
  ```
  Alerts fired: 47
  SL hits: 12
  T1 hits: 8
  T2 hits: 3
  T3 hits: 1
  Win rate: 32% (expected 55% for simulation)
  No crashes ✓
  ```

### Task 5.2: Feature Extraction Validation
- **What:** Verify all 79 features are correctly populated
- **How:** Dump sample feature record, spot-check values
  ```python
  sample = db.get_ml_dataset(limit=1)[0]
  for feature in FEATURE_COLUMNS:
      assert feature in sample, f"{feature} missing"
      assert not pd.isna(sample[feature]), f"{feature} is NaN"
  ```
- **Why:** Catch corrupted features before model training
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Low
- **Expected Output:** All 79 features validated ✓

### Task 5.3: Model Inference Load Test
- **What:** Call model.predict() 1000 times, measure latency
- **How:**
  ```python
  import timeit
  times = []
  for i in range(1000):
      t0 = time.time()
      pred = model.predict(X_sample)
      times.append(time.time() - t0)
  print(f"Mean: {np.mean(times)*1000:.1f}ms, Std: {np.std(times)*1000:.1f}ms")
  ```
- **Why:** Ensure <100ms inference for real-time signals
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Mean latency ~45ms ✓

### Task 5.4: Broker API Integration Test (Mock + Real)
- **What:** Test all broker methods with mock + real Fyers credentials
- **How:** Run test suite against both mock broker + Fyers
- **Why:** Catch API format/auth issues before live
- **Time:** 30 min
- **Risk:** Medium (real API calls)
- **Effort:** Medium
- **Expected Output:** 
  ```
  Mock Broker: 20/20 tests pass ✓
  Fyers Broker: 19/20 tests pass (1 skipped due to Fyers outage)
  ```

### Task 5.5: Paper Trading 24-Hour Run
- **What:** Run app in paper trading mode for full market day
- **How:** Start at 9:15 IST, monitor until 15:30 IST
- **Why:** Catch real-time bugs before live
- **Time:** 6h wall-clock (but async in background)
- **Risk:** Medium
- **Effort:** High (monitoring required)
- **Expected Output:** 
  ```
  Alerts: 23 EARLY_MOVE, 6 TRADE_SIGNAL
  Paper Trades Placed: 6
  P&L: +50 to -75 points
  No crashes ✓
  Database populated with real data ✓
  ```

### Task 5.6: Stress Test (Rapid Updates)
- **What:** Send 100 market ticks per second, verify no data loss
- **How:** Mock broker sends spot prices at 100Hz
- **Why:** Catch race conditions, queue overflows
- **Time:** 10 min
- **Risk:** Low (mock only)
- **Effort:** Low
- **Expected Output:** All ticks processed, no exceptions ✓

### Task 5.7: Database Integrity Check
- **What:** Verify referential integrity, no orphaned records
- **How:** Run SQL checks:
  ```sql
  -- Check for orphaned alerts
  SELECT * FROM ml_feature_store 
  WHERE alert_id NOT IN (SELECT id FROM alerts);
  ```
- **Why:** Catch data corruption
- **Time:** 10 min
- **Risk:** Very Low
- **Effort:** Trivial
- **Expected Output:** Zero orphaned records ✓

### Task 5.8: Recovery Test (Crash Simulation)
- **What:** Kill app mid-trade, restart, verify state recovery
- **How:**
  1. Place paper trade
  2. Kill process mid-signal
  3. Restart app
  4. Verify trade rehydrated + continuing
- **Why:** Ensure graceful recovery from crashes
- **Time:** 15 min
- **Risk:** Low
- **Effort:** Medium
- **Expected Output:** Trade state recovered correctly ✓

---

## **PHASE 6: DOCUMENTATION & HANDOFF** (60 minutes)

### Task 6.1: Final Diagnostic Report
- **What:** Run diagnostic.py after all fixes, gen comprehensive report
- **How:** python diagnostic.py > FINAL_STATUS_2026-04-02.txt
- **Time:** 5 min
- **Expected Output:** All systems ✓

### Task 6.2: User Quick-Start Guide
- **What:** 5-page guide: setup → paper trading → live trading
- **How:** Markdown with screenshots
- **Time:** 20 min
- **Expected Output:** QUICKSTART.md

### Task 6.3: API Documentation
- **What:** Document all public methods (DataManager, ModelManager, etc.)
- **How:** Docstrings + markdown
- **Time:** 15 min
- **Expected Output:** API_REFERENCE.md

### Task 6.4: Configuration Guide
- **What:** Explain what each config parameter does + how to tune
- **How:** Inline comments + CONFIG_GUIDE.md
- **Time:** 10 min
- **Expected Output:** CONFIG_GUIDE.md

### Task 6.5: Troubleshooting Guide
- **What:** 20 common issues + resolutions
- **How:** FAQ format
- **Time:** 10 min
- **Expected Output:** TROUBLESHOOTING.md

---

## **SUMMARY BY METRICS**

| Phase | Tasks | Time | Effort | Risk |
|---|---|---|---|---|
| **1: Database** | 7 | 90 min | Low | Low |
| **2: Broker** | 10 | 150 min | Medium | Medium |
| **3: ML** | 12 | 240 min | High | Medium |
| **4: Code** | 10 | 180 min | High | Low |
| **5: Testing** | 8 | 120 min | High | High |
| **6: Docs** | 5 | 60 min | Low | Very Low |
| **TOTAL** | **52 Tasks** | **840 min (14 hrs)** | **High** | **Medium** |

---

## **DELIVERY TIMELINE**

```
Day 1 (Tue, Apr 2):
  ├─ Phase 1: Database (90 min) ✓
  ├─ Phase 2: Broker (part 1) (60 min)
  └─ Phase 3: ML audit (30 min)
  Total: 3.5 hours

Day 2 (Wed, Apr 3):
  ├─ Phase 2: Broker (part 2) (90 min)
  ├─ Phase 3: Model training v29 (45 min)
  ├─ Phase 4: Error handling (45 min)
  └─ Phase 5: Mock 24h test (30 min)
  Total: 3.25 hours

Day 3 (Thu, Apr 4):
  ├─ Phase 3: Tuning + cross-val (90 min)
  ├─ Phase 4: Unit tests (60 min)
  ├─ Phase 5: Paper trading 24h test (6h wall-clock, async)
  └─ Phase 6: Documentation (60 min)
  Total: 4 hours (+ 6h monitoring)

Day 4 (Fri, Apr 5):
  ├─ Phase 5: Recovery + stress tests (30 min)
  ├─ Final validation (30 min)
  ├─ Sign-off (30 min)
  └─ Buffer for issues (60 min)
  Total: 2.5 hours

TOTAL WORK TIME: ~13-15 hours
TOTAL CALENDAR TIME: 4 days
```

---

## **SUCCESS CRITERIA**

### ✅ Go-Live Checklist

- [ ] Database: 9 tables, all indices created, 0 data loss
- [ ] Broker: Fyers API working, health check <100ms
- [ ] ML: Model v29 F1 ≥ 0.70, recall ≥ 0.75
- [ ] Paper Trading: 24h run with 0 crashes
- [ ] Alerts: Firing correctly, deduplication working
- [ ] Logging: All errors captured, no silent failures
- [ ] Unit Tests: 20/20 passing
- [ ] Monitoring: Dashboard showing real-time stats
- [ ] Documentation: 5 guides complete + reviewed
- [ ] Performance: End-to-end latency <100ms

### 🔴 Blockers (Stop if not met)

- ML F1 < 0.65 → Retrain or investigate
- Any crashes during 24h test → Debug & fix
- Broker integration fails → Troubleshoot
- Database corruptions → Rollback & restart

---

## **APPROVAL REQUIRED**

**User approval needed before starting:**

- [ ] Do you approve Phase 1 (Database recovery)?
- [ ] Do you approve Phase 2 (Broker integration)?
- [ ] Do you approve Phase 3 (ML retraining)?
- [ ] Do you approve Phase 4-6 (Testing + Docs)?
- [ ] Do you understand the risks (loss possible on live)?
- [ ] Do you commit to 1h/day monitoring for first week?

---

**Ready to start?** Confirm approval and I begin immediately. 🚀
