# NiftyTrader Troubleshooting Guide

## Common Issues & Solutions

### 1. Fyers Token Expired
**Symptom:** Logs show "Fyers token EXPIRED Xh ago"
**Fix:** Go to Credentials tab → Select "Fyers" → Click "Generate Auth URL" → Login in browser → Paste auth code back → Save

### 2. No Signals Firing
**Symptom:** App runs but no alerts, no signals
**Cause:** VIX too high, ML confidence below threshold, or not enough engines agreeing
**Fix:**
- Check India VIX (must be <25 for BULLISH, <28 for BEARISH signals)
- Check min engines setting (default: 4)
- Check logs for "Trade Signal blocked" messages

### 3. Database Empty / No Tables
**Symptom:** App crashes with "no such table" errors
**Fix:**
```bash
cd d:\nifty_trader_v3_final\nifty_trader
python -c "from database.manager import get_db; db=get_db(); print('DB OK')"
```
This recreates the schema if empty.

### 4. ML Model F1 Score Low (<0.5)
**Symptom:** model_vX has F1=0.30-0.45
**Cause:** Class imbalance (too many loss labels from ATR heuristic)
**Fix:** Wait for more P1/P2 label data (real TradeOutcome records). Alternatively, lower ML_CONFIDENCE_THRESHOLD from 0.60 to 0.55.

### 5. App Crashes on Startup
**Symptom:** PySide6 crash or ImportError
**Fix:**
```bash
pip install PySide6 xgboost scikit-learn pandas numpy fyers-apiv3
```

### 6. 429 Rate Limit Errors (9:00-9:15 AM)
**Symptom:** Logs show "Fyers rate limited (429)"
**Cause:** Fyers API rejects calls during pre-open session
**Fix:** Normal behavior — circuit breaker handles it. Market data only available from 9:15 AM.

### 7. "Database is locked" Errors
**Symptom:** SQLite locked errors during concurrent access
**Fix:** DB uses WAL mode with 60s timeout. If persisting, close all other SQLite browsers pointing at nifty_trader.db.

### 8. High Memory Usage
**Symptom:** App using >1GB RAM
**Cause:** Large option chain snapshots table (19K+ rows)
**Fix:** Periodically clean old snapshots: run scripts/check_db_integrity.py and manually delete rows older than 30 days.

### 9. No Candle Data on Startup
**Symptom:** "Bootstrap failed" or 0 candles loaded
**Cause:** Fyers API down or token expired
**Fix:** Check token expiry, verify Fyers API status. App uses 15-min delay after market open.

### 10. Telegram Alerts Not Sending
**Symptom:** Alerts fire in UI but Telegram silent
**Fix:** Check config.py: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set. Test: `python -c "from alerts.telegram_alert import send_telegram; send_telegram('test')"`.

### 11. Model Retraining Takes Too Long
**Symptom:** Retraining hangs for >10 minutes
**Cause:** Large dataset (70K+ records) + GridSearch
**Fix:** Lower ML_MIN_SAMPLES_TO_ACTIVATE or reduce XGBoost n_estimators from 200 to 100.

### 12. SENSEX/MIDCPNIFTY Not Showing
**Symptom:** Only NIFTY and BANKNIFTY in signals
**Fix:** Check config.py INDICES list. SENSEX requires BSE broker support (Fyers supports it).

### 13. Wrong Expiry Dates
**Symptom:** Wrong option strikes, wrong expiry shown
**Cause:** Expiry calendar not updated after SEBI changes
**Fix:** Check nifty_trader/data/expiry_calendar.py for the correct weekly expiry days.

### 14. S11 Monitor Not Firing
**Symptom:** S11 tab empty, no auto paper trades
**Fix:** S11 requires at least 3 consecutive matching alerts. Check: min_consecutive_alerts setting in config.

### 15. Import Errors on First Run
**Symptom:** ModuleNotFoundError for internal modules
**Fix:** Always run from the nifty_trader/ subfolder:
```bash
cd d:\nifty_trader_v3_final\nifty_trader
python main.py
```

### 16. High CPU Usage
**Symptom:** CPU >50% constantly
**Cause:** Too-frequent data polling
**Fix:** Increase tick interval in config or reduce number of active engines.

### 17. Option Chain Not Updating
**Symptom:** PCR/OI data stale, not refreshing
**Cause:** Fyers option chain API returning cached data
**Fix:** Normal during pre-market. Live data starts at 9:15 AM.

### 18. Cannot Place Paper Trades
**Symptom:** S11 monitor never places trades
**Fix:** Ensure PAPER_TRADING_MODE=True in config.py. Check s11_paper_trades table for entries.

### 19. Model Not Found After Fresh Install
**Symptom:** "No model loaded, collecting data"
**Cause:** models/ folder empty — need to accumulate labeled data first
**Fix:** Let app run for 2-3 market days. AutoLabeler will label records. Model trains after MIN_SAMPLES_TO_ACTIVATE (default: 200) labeled records.

### 20. Git Push Rejected
**Symptom:** `git push` fails with "non-fast-forward"
**Fix:**
```bash
git pull --rebase origin main
git push origin master:main
```
