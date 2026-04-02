# LIVE TRADING RUNBOOK

**NiftyTrader v3 — Production Live Trading Procedures**

---

## 📋 QUICK REFERENCE

| Component | Status Check | Command |
|-----------|--------------|---------|
| Database | 9 tables present | `python -c "from database.manager import get_db; db=get_db(); print(f'Tables: {len(db.get_table_list())}')"` |
| Model | F1 ≥ 0.70 | `python -c "from ml.model_manager import get_model_manager; m=get_model_manager(); print(f'F1: {m._model_version.metrics[\"f1\"]:.3f}')"` |
| Broker | Connected | `python -c "from data.data_manager import get_data_manager; dm=get_data_manager(); print(f'NIFTY: {dm.get_spot_price(\"NIFTY\")}')"` |
| Pre-Live | All checks ✓ | `python nifty_trader/trading/pre_live_checklist.py` |

---

## 🌅 DAILY STARTUP PROCEDURE (9:15 AM IST)

### Step 1: System Pre-Checks (9:15 - 9:20 AM)

```bash
# Terminal 1: Run pre-live verification
cd d:\nifty_trader_v3_final
python nifty_trader/trading/pre_live_checklist.py
```

**Expected Output:**
```
✓ Database healthy
✓ Broker connected  
✓ Model ready
✓ Live gate configured
✓ Auto stop-loss ACTIVE
✓ Backup database exists
✓ Logging active

✅ ALL CHECKS PASSED - Ready for live trading!
```

**If ANY check fails:** 
- ❌ **STOP** — Do NOT start trading
- 🔧 Fix the issue (see Troubleshooting section)
- ⏭️ Rerun pre-live checklist

### Step 2: Broker Credential Verification (9:15 AM)

1. Open NiftyTrader UI
2. Click **Credentials** tab
3. Verify:
   - [ ] "Fyers" broker is selected
   - [ ] "Token expires in X hours" shows > 1 hour
   - [ ] If < 1 hour: Click **Re-authenticate** now

### Step 3: Check Live Mode Setting

```python
# Verify in config.py:
LIVE_TRADING_MODE = True    # ✓ Must be True
PAPER_TRADING_MODE = False  # ✓ Must be False
AUTO_STOP_LOSS_ENABLED = True  # ✓ Must be True
```

### Step 4: Monitor Dashboard (9:20 - 9:30 AM)

1. Click **Live Trading** tab
2. Verify all systems green:
   - [ ] Open Trades: 0
   - [ ] Daily P&L: ₹0
   - [ ] Status: Ready
3. Watch logs for any startup errors

**Common startup messages (NORMAL):**
```
✓ Database connected
✓ ML model v28 loaded (F1=0.72)
✓ Fyers connected - NIFTY: 23500
✓ Bootstrap: 125 candles/index
✓ Data thread: Running
✓ Candle thread: Running
✓ AutoStopLoss monitoring: Started
```

---

## 📈 DURING MARKET HOURS (9:30 AM - 3:30 PM IST)

### Normal Operation Flow

```
Signal Generated (Every 3-5 min)
    ↓
Gate Checks (ML confidence, risk limits, time)
    ↓
If PASS → Popup Notification
    ↓
User Confirmation Dialog (30 sec to confirm)
    ↓
If CLICKED "CONFIRM" → Place Order
    ↓
Order Execution (Market price)
    ↓
Dashboard updates instantly
    ↓
Monitor position in real-time
```

### During Each Signal

**When you see a 🔔 signal notification:**

1. **READ the popup:**
   - Symbol: NIFTY/BANKNIFTY/etc
   - Direction: BULLISH/BEARISH
   - ML Confidence: Must be > 55%
   - Entry Price, SL, Targets

2. **QUICK DECISION (30 seconds):**
   - ✓ Click CONFIRM if you trust the signal
   - ✗ Click CANCEL to skip (no penalty)

3. **ASK YOURSELF:**
   - Is market direction matching the signal?
   - Has anything unusual happened?
   - Do I want exposure right now?

4. **What happens next:**
   - ✓ Confirmed → Order placed immediately at market
   - ✗ Cancelled → Nothing happens, wait for next signal
   - ⏱️ 30s timeout → Automatically cancelled (safe default)

### Monitoring Open Position

**Once trade is placed:**

1. Watch Dashboard:
   - Real-time PnL (updates every 2 sec)
   - Current price vs Entry price
   - Profit/Loss color indicator

2. **You don't need to do anything:**
   - Stop-loss is AUTO-EXECUTED (no manual action)
   - Targets T1, T2, T3 are tracked automatically
   - Database records entry/exit automatically

3. **If you're concerned:**
   - Click 🚨 **EMERGENCY EXIT** button
   - All positions close instantly

### Daily Loss Limit Enforcement

**Daily Loss Threshold: ₹5,000**

If daily loss reaches ₹5,000:
- 🚨 Trading automatically HALTS
- All existing positions remain open
- No new signals will execute
- User alerted via:
  - 🔴 Dashboard turns RED
  - 📢 Desktop notification
  - 📱 Telegram alert (if configured)

**Action if halted:**
- Review performance (see Daily Statistics)
- Decide whether to continue (manual config change)
- Or wait until next market day (stats reset)

---

## 🎯 DURING POSITION MANAGEMENT

### Position is Making Money (Green)

✓ **Let it run** — The system is working
- Wait for target (T1, T2, or T3)
- Dashboard will show when target hits
- Exit gets recorded automatically

### Position is Losing Money (Red)

**Option 1: Let stop-loss execute**
- System will auto-close at SL price
- Loss will be recorded
- Next signal can be placed

**Option 2: Manual close (if something's wrong)**
- Click 🚨 **EMERGENCY EXIT**
- All positions close immediately

### Multiple Open Positions

Max concurrent trades: **2 lots**

If you already have 2 open:
- Next signal will be BLOCKED by gate
- Message: "Already 2 open trades (max 2)"
- Wait for one to close first

---

## 📊 REAL-TIME DASHBOARD MONITORING

### Metrics Explained

| Metric | What It Means | Action |
|--------|---------------|--------|
| **Open Trades** | Number of live positions | Max 2 — close one if equals 2 |
| **Daily P&L** | Today's total profit/loss | Red = loss, Green = profit |
| **Win Rate** | % of closed trades that won | Aim for >45% long-term |
| **Daily Loss** | Running loss total | Red at ₹5,000 (hard stop) |

### PnL Bar (Visual Indicator)

```
╔════════════════════════════════════╗
║   Current: ₹2,500 / Daily Max: ₹5,000
║   ████████░░░░░░░░░░  50% of limit
│ -5000                            +10000
│   RED                 GREEN
```

- **GREEN** = Making money ✓
- **YELLOW** = 50% of loss limit reached ⚠️
- **RED** = Near/at loss limit 🛑

---

## ⏰ END-OF-DAY PROCEDURE (3:45 PM - 4:00 PM IST)

### Step 1: Market Close Automation (3:30 PM)

The system automatically:
```
15:30 IST → Check all open positions
15:31 IST → Close any remaining positions at market
15:32 IST → Record all trades in database
```

**You DON'T need to do anything** — It's automatic.

### Step 2: End-of-Day Review (After 3:45 PM)

1. Check Final P&L:
   ```
   Dashboard shows: "Daily P&L: ₹X,XXX"
   ```

2. Review Daily Statistics:
   - Total trades: ?
   - Win rate: ?  
   - Largest win: ?
   - Largest loss: ?

3. Verify all positions closed:
   - Dashboard: "Open Trades: 0"
   - Database: Check trade_outcomes table

### Step 3: Create Backup

```bash
# Weekly backup (recommended Friday)
cp d:\nifty_trader_v3_final\niftytrader.db niftytrader.db.backup-$(date +%Y%m%d)
```

### Step 4: Review Logs

```bash
# Check today's log file
Get-Content logs/niftytrader_*.log | Select-Object -Last 50
```

**Look for:**
- ✓ No ERROR messages
- ✓ No EXCEPTION messages  
- ⚠️  If found, investigate before tomorrow

---

## 🚨 EMERGENCY PROCEDURES

### Situation: Position Has Gone Wrong

**Option 1 - Click 🚨 Button**
```
Dashboard → [🚨 EMERGENCY EXIT - CLOSE ALL POSITIONS]
Confirms: "Close ALL positions?"
Click: YES
Result: All positions closed at market price
```

**Option 2 - Manual Fyers Close**
```
1. Open Fyers mobile app / web
2. Find your position
3. Click SELL / EXIT
4. Close at market
```

### Situation: System Crash

**If app crashes:**
```
1. Check database: niftytrader.db
2. Check last position: SELECT * FROM trade_outcomes WHERE status='OPEN'
3. If positions still open in Fyers → Close manually
4. Clear halt file: rm auth/trading.halt
5. Restart app
```

### Situation: Internet Lost Connection

**If connection drops:**
- Stop-loss will still execute (at Fyers server level)
- Reconnect automatically when connection restored
- Check dashboard for position status

### Situation: Daily Loss Limit Hit

**If ₹5,000 loss reached:**
```
Dashboard: "Daily Loss: ₹5,000 / ₹5,000 ⛔"
Status: Trading HALTED

Options:
A) Stop trading for rest of day (Recommended)
B) Manually re-enable in config.py (Advanced)
C) Wait until next market day - stats auto-reset
```

---

## 📱 ALERT TYPES & WHAT THEY MEAN

### Dashboard Alerts

| Alert | Meaning | Action |
|-------|---------|--------|
| 🔴 Live Signal | Signal passed gate, awaiting confirmation | Confirm or Cancel |
| ⚠️  Order Blocked | Gate denied order (confluence issues) | Wait for next signal |
| ✓ Order Placed | Your order is now live | Monitor dashboard |
| 🚨 SL Triggered | Stop-loss hit, position closing | Review in dashboard |
| 🛑 Daily Loss Limit | ₹5,000 loss reached | Trading halted |

### Desktop Notifications

- **Signal Alert**: "NIFTY BULLISH - ML: 62%"
- **Order Placed**: "LIVE: NIFTY BUY @ 23500"
- **Stop-Loss Hit**: "SL TRIGGERED: NIFTY @ 23450"
- **Daily Limit**: "DAILY LOSS LIMIT EXCEEDED - Trading Halted"

### Telegram Alerts (if configured)

```
🔔 NIFTY BULLISH | ML: 62% | Entry: 23500 | SL: 23450
✓ LIVE: Bought @ 23-500
🚨 SL: Closed @ 23450 | P&L: -₹3250
```

---

## 🔧 TROUBLESHOOTING

### "Broker NOT authenticated - OAuth required"

**Solution:**
```
1. Dashboard → Credentials tab
2. Click [Re-authenticate]
3. Browser opens → Log in to Fyers
4. Authorization complete
5. Return to app
```

### "Insufficient buying power: ₹40,000"

**Solution:**
- Add more funds to Fyers account (min ₹50,000)
- Or reduce position size in config.py

### "Database FAILED - No tables found"

**Solution:**
```bash
cd d:\nifty_trader_v3_final
python nifty_trader/database/manager.py --init
```

### "Model FAILED or F1 < 0.65"

**Solution:**
```
1. Wait for model to retrain (happens auto every 50 labels)
2. Check database has labeled samples:
   SELECT COUNT(*) FROM trade_outcomes WHERE label IS NOT NULL
3. If < 50, system retrains when reaching threshold
```

### "Circuit Breaker: Extreme volatility detected"

**This is NORMAL during:**
- Market gap opens
- Major economic news
- Sudden crashes

**Action:** Wait 15 min, resume trading after volatility settles

### "AutoStopLoss DISABLED"

**Solution:**
```python
# Edit config.py
AUTO_STOP_LOSS_ENABLED = True  # Change to True
```

### Dashboard shows "Open Trades: 2" but you want to trade

**Solution:**
- Wait for one position to close (SL or T1/T2/T3 hit)
- Or click 🚨 EMERGENCY EXIT to close all first

---

## ✅ DAILY CHECKLIST

Print this and use daily:

```
□ 9:15 AM - Run pre-live checklist (all checks ✓)
□ 9:15 AM - Check Fyers token < 2 hours to expiry
□ 9:20 AM - Dashboard shows all systems green
□ 9:30 AM - Ready to trade
□ After each signal - Review confirmation dialog before clicking CONFIRM
□ During day - Monitor P&L (check every 30 min)
□ 3:30 PM - All positions auto-close (verify 0 open trades)
□ 3:45 PM - Review daily statistics
□ 4:00 PM - Check logs for errors
□ Weekly - Create backup of database
```

---

## 📞 SUPPORT / ESCALATION

| Issue | Action |
|-------|--------|
| **Question about signal** | Check signal_aggregator.py documentation |
| **Model not loading** | Check ml/model_manager.py logs |
| **Broker order fails** | Check data/adapters/fyers_adapter.py |
| **Database error** | Check database/manager.py migration logs |
| **AI agent stuck** | Kill process, restart app, check logs |

---

## 🔒 SAFETY REMINDERS

- ✋ **NEVER** disable AUTO_STOP_LOSS_ENABLED
- ✋ **NEVER** increase MAX_DAILY_LOSS_RUPEES without strong reason
- ✋ **NEVER** skip pre-live checklist
- ✋ **NEVER** trade with borrowed money
- ✋ **NEVER** leave system unattended for > 1 hour

---

## 📈 EXPECTED OUTCOMES

**After 20 trading days:**

| Metric | Target | Status |
|--------|--------|--------|
| Win Rate | >45% | If <45%, ML needs retraining |
| Profit Factor | >1.5:1 | If <1.5, adjust position size down |
| Max Drawdown | < 20% | If >20%, increase SL distance |
| Daily Average | +₹500-1000 | Adjust targets if not hitting |

---

**Last Updated:** 2026-04-02  
**Version:** 1.0  
**Status:** PRODUCTION READY
