# LIVE TRADING - COMPREHENSIVE SETUP GUIDE

**NiftyTrader v3 Production Ready**  
**Document Version:** 1.0  
**Last Updated:** 2026-04-02  
**Status:** ✅ DEPLOYMENT READY

---

## TABLE OF CONTENTS

1. [Overview & Architecture](#overview)
2. [Safety Mechanisms](#safety)
3. [Pre-Live Checklist](#pre-live)
4. [Configuration Settings](#config)
5. [Deployment Steps](#deployment)
6. [Daily Operations](#operations)
7. [Risk Management](#risk)
8. [Emergency Procedures](#emergency)
9. [Monitoring & Logging](#monitoring)
10. [FAQ & Troubleshooting](#faq)

---

## <a name="overview"></a>1. OVERVIEW & ARCHITECTURE

### What is Live Trading Mode?

Live trading means:
- ✅ Real money deployed to Fyers account
- ✅ Real orders placed and executed
- ✅ Real profits and losses recorded
- ⚠️ Losses are possible and real

### Key Components Deployed

| Component | Purpose | File | Status |
|-----------|---------|------|--------|
| **Live Gate** | Blocks unsafe orders | `trading/live_gate.py` | ✅ Created |
| **Auto Stop-Loss** | Auto-closes losing trades | `trading/auto_stop_loss.py` | ✅ Created |
| **Position Sizer** | Calculates safe position size | `trading/position_sizer.py` | ✅ Created |
| **Daily PnL Tracker** | Tracks daily P&L | `trading/daily_pnl_tracker.py` | ✅ Created |
| **Account Verifier** | Pre-checks broker account | `trading/account_verifier.py` | ✅ Created |
| **Circuit Breaker** | Stops on extreme volatility | `trading/account_verifier.py` | ✅ Created |
| **Live Dashboard** | Real-time monitoring | `ui/live_trading_dashboard.py` | ✅ Created |
| **Order Confirmation** | Manual order approval | `ui/live_order_confirmation_dialog.py` | ✅ Created |
| **Disclaimer Dialog** | Risk acknowledgment | `ui/live_trading_disclaimer_dialog.py` | ✅ Created |

---

## <a name="safety"></a>2. SAFETY MECHANISMS

### ✅ Seven Layers of Safety

#### Layer 1: Configuration Lockdown
```python
# config.py - These are ENFORCED
LIVE_TRADING_MODE = False  # User manually sets to True
PAPER_TRADING_MODE = True  # Paper mode is default
POSITION_SIZE_CONTRACTS = 1  # Max 1 lot per trade
MAX_CONCURRENT_TRADES = 2  # Max 2 open simultaneously
MAX_DAILY_LOSS_RUPEES = 5000  # Hard stop at 5k loss
AUTO_STOP_LOSS_ENABLED = True  # MANDATORY - cannot disable
EMERGENCY_EXIT_THRESHOLD = 2.5  # Circuit breaker trigger
```

#### Layer 2: Live Gate Checks
Before placing ANY order:
1. **Live Mode Check** — Must be explicitly enabled
2. **ML Confidence** — Must exceed 55% threshold
3. **Market Hours** — Only 9:30-14:45 IST
4. **Position Limit** — Max 2 concurrent trades
5. **Daily Loss Limit** — Can't exceed ₹5,000
6. **Circuit Breaker** — Blocks if ATR spikes >300%

#### Layer 3: Manual Confirmation Dialog
```
User sees:
  • Order symbol, quantity, direction
  • Entry price, SL, targets
  • ML confidence score
  • Must click CONFIRM to proceed
  • Dialog warns: "This places REAL money order"
  • Default button is CANCEL (safer UX)
  • Double-confirms on final button click
```

#### Layer 4: Auto Stop-Loss Execution
- Runs in background thread (every 5 sec)
- Monitors all open positions
- If current price ≤ SL → Auto-executes close order
- User does NOT need to manually close
- Prevents holding losing positions overnight

#### Layer 5: Daily Loss Limit Enforcement
```
Daily Loss Tracking:
  • P&L calculated after each trade closes
  • Running total tracked throughout day
  • At ₹5,000 loss → All trading HALTS
  • New signals REJECTED with: "Daily loss limit exceeded"
  • Prevents catastrophic drawdowns
  • Resets automatically next trading day
```

#### Layer 6: Circuit Breaker (Black Swan Protection)
Automatically triggered if:
- ATR spikes > 300% above 20-day average
- OR spot price moves > 500 points in 5 minutes
- When triggered:
  - All new signals rejected
  - No new orders placed
  - Existing positions remain (but no new exposure)
  - Waits for market to stabilize

#### Layer 7: Emergency Exit Button
- Big red button on dashboard: 🚨 **EMERGENCY EXIT**
- Closes ALL positions immediately at market
- No confirmation (intentionally to save time)
- Use only when something is WRONG

---

## <a name="pre-live"></a>3. PRE-LIVE CHECKLIST

### Must Complete Before First Trade

```bash
# Run this command - ALL MUST PASS
python nifty_trader/trading/pre_live_checklist.py
```

**Checks:**
- [ ] ✓ Database healthy (9 tables present)
- [ ] ✓ Broker connected (can fetch NIFTY price)
- [ ] ✓ Model ready (F1 ≥ 0.65)
- [ ] ✓ Live gate configured (gate exists)
- [ ] ✓ Auto stop-loss enabled (TRUE in config)
- [ ] ✓ Backup database exists
- [ ] ✓ Logging active (today's logs present)

**From User:**
- [ ] Paper traded for 5+ days
- [ ] Have ₹50,000+ in Fyers account
- [ ] Read all documentation
- [ ] Understand risks of ₹5,000 daily loss limit
- [ ] Acknowledged disclaimer dialog

### Account Verification

```bash
python -c "
from trading.account_verifier import AccountVerifier
from data.adapters.fyers_adapter import FyersAdapter

broker = FyersAdapter()
success, results = AccountVerifier.verify_fyers_account(broker)

if success:
    print(f'✓ Account verified')
    print(f'  Buying Power: ₹{results[\"buying_power\"]:,.0f}')
    print(f'  Can place orders: {results[\"can_place_orders\"]}')
else:
    print(f'✗ Account verification failed')
    for error in results['errors']:
        print(f'  - {error}')
"
```

---

## <a name="config"></a>4. CONFIGURATION SETTINGS

### Critical Settings (Must Review)

```python
# File: nifty_trader/config.py

# ⚠️ LIVE TRADING - User must set to True
LIVE_TRADING_MODE = False  # Set to True ONLY after all checks pass

# Paper trading (safety mode) - keep True for testing
PAPER_TRADING_MODE = True  # Set to False when going live

# Position sizing
POSITION_SIZE_CONTRACTS = 1  # Start with 1 lot only
MAX_CONCURRENT_TRADES = 2  # NEVER increase this
MAX_DAILY_LOSS_RUPEES = 5000  # Hard limit - very important

# Risk management
AUTO_STOP_LOSS_ENABLED = True  # MUST be True - never disable
REQUIRED_MODEL_CONFIDENCE = 0.55  # Min 55% ML score to trade
EMERGENCY_EXIT_THRESHOLD = 2.5  # Circuit breaker (ATR × 2.5)

# Trading hours IST (UTC+5:30)
LIVE_TRADING_START_TIME = "09:30"  # Market open + 15 min
LIVE_TRADING_STOP_TIME = "14:45"  # 45 min before close
LIVE_TRADING_STOP_LOSS_TIME = "15:20"  # Final emergency close

# Monitoring
MONITOR_DASHBOARD_PORT = 8000  # Dashboard at http://localhost:8000
```

### How to Enable Live Mode

```python
# STEP 1: Edit config.py
LIVE_TRADING_MODE = False  # ← Change this to True

# STEP 2: Restart app
# Kill running instance and restart

# STEP 3: Dashboard shows status
# "🟥 Status: LIVE TRADING ENABLED"

# STEP 4: First signal shows confirmation
# Proceed when you're ready
```

---

## <a name="deployment"></a>5. DEPLOYMENT STEPS

### Quick Deployment (5 minutes)

```bash
# Terminal 1: Backup database
cp niftytrader.db niftytrader.db.backup-$(date +%Y%m%d_%H%M%S)

# Terminal 2: Run deployment script
cd d:\nifty_trader_v3_final
python scripts/deploy_live.py

# Terminal 3: Open app
python nifty_trader/main.py
```

### Manual Deployment (Detailed Steps)

**Step 1: Database Backup (9:00 AM)**
```bash
cp d:\nifty_trader_v3_final\niftytrader.db d:\nifty_trader_v3_final\niftytrader.db.backup-2026-04-02
echo "✓ Backup complete"
```

**Step 2: Pre-Live Verification (9:10 AM)**
```bash
python nifty_trader/trading/pre_live_checklist.py
# Expected: ALL CHECKS PASSED
```

**Step 3: Configuration Update (9:15 AM)**
```python
# Edit: nifty_trader/config.py
# Line: LIVE_TRADING_MODE = False
# Change to: LIVE_TRADING_MODE = True
# Save file
```

**Step 4: Restart Application (9:20 AM)**
```bash
# Kill running app (Ctrl+C)
# Restart:
python nifty_trader/main.py
```

**Step 5: Dashboard Verification (9:25 AM)**
```
Open: Live Trading tab
Verify:
  ✓ Open Trades: 0
  ✓ Daily P&L: ₹0
  ✓ Status: LIVE TRADING ENABLED (red text)
  ✓ Auto stop-loss: Active
```

**Step 6: Broker Check (9:25 AM)**
```
Click: Credentials tab
Verify:
  ✓ Broker: Fyers
  ✓ Token expires in: > 1 hour
  ✓ If < 1 hour: Click Re-authenticate
```

**Step 7: Ready for Market Open (9:30 AM)**
```
Watch: Dashboard for first signal
When signal arrives:
  ✓ Confirmation dialog shows
  ✓ Review order details
  ✓ Click CONFIRM to place live order
  ✓ Dashboard updates with position
```

---

## <a name="operations"></a>6. DAILY OPERATIONS

### Morning Checklist (9:15 - 9:30 AM)

```
□ Run pre-live checklist (all must PASS)
□ Check Fyers token (< 2 hours to expiry)
□ Open dashboard (verify all systems green)
□ Check broker connection (NIFTY price visible)
□ Review daily loss limit (₹5,000 shown)
□ Verify auto stop-loss (ENABLED)
□ Check logs (no ERROR messages)
□ Ready for market open (9:30 AM)
```

### During Market Hours (9:30 AM - 3:30 PM)

**Signal Flow:**
```
1. Signal generated (every 3-5 minutes)
   ↓
2. Gate validates (ML conf, risk, hours)
   ↓
3. Confirmation dialog appears (🔔 notification)
   ↓
4. User reviews (30 seconds to decide)
   ↓
   A. Click CONFIRM → Order placed at market
   B. Click CANCEL → Skip signal (wait for next)
   C. Timeout (30s) → Auto-cancelled (safe default)
   ↓
5. Order executes (if confirmed)
   ↓
6. Dashboard updates (real-time PnL)
   ↓
7. Monitor position (wait for SL or target)
   ↓
8. Exit auto-executes (SL or T1/T2/T3 hit)
   ↓
9. Outcome recorded in database
   ↓
10. Next signal (process repeats)
```

**What You Watch:**
- Real-time P&L (green = profit, red = loss)
- Daily total P&L (stop at ₹5,000 loss)
- Open positions count (max 2)
- Broker connection status

**What You DON'T Do:**
- ✋ Don't manually close trades (auto stop-loss does it)
- ✋ Don't try to "pick" which signals to skip (gate does it)
- ✋ Don't monitor every second (check every 30 min)
- ✋ Don't panic (circuit breaker handles crashes)

### Evening Checklist (3:45 - 4:00 PM)

```
□ Market closed (3:30 PM IST)
□ All positions auto-closed (verify 0 open)
□ Daily P&L visible in dashboard
□ Review daily statistics:
  - Total trades: ?
  - Win rate: ?
  - Largest win: ?
  - Largest loss: ?
  - Daily total: ? (should be positive most days)
□ Check logs (any errors?)
□ Backup database (weekly minimum)
□ Tomorrow morning: Run pre-live checklist again
```

---

## <a name="risk"></a>7. RISK MANAGEMENT

### Position Sizing Formula

```
Max Loss = Account Equity × Risk Percent
Contracts = Max Loss / (SL Points × Lot Size × 1 Point Value)

Example:
  Account Equity: ₹5,00,000
  Risk Percent: 1%
  SL Distance: 50 points
  NIFTY Lot Size: 65
  1 Point Value: 65 rupees
  
  Max Loss = 5,00,000 × 1% = ₹5,000
  Contracts = 5,000 / (50 × 65) = 5,000 / 3,250 = 1.54 lots → 1 lot
```

### Risk-Reward Ratio Target

```
Target Minimum Ratio: 1:1.5
  • Risk (SL): ₹3,000
  • Reward (T1): ₹4,500+

Example Trade Sizing:
  • Entry: NIFTY 23,500
  • SL: 23,450 (50 points down)
  • T1: 23,575 (75 points up)
  • T2: 23,650 (150 points up)
  • T3: 23,750 (250 points up)
  
  Risk = 50 × 65 = ₹3,250
  Reward T1 = 75 × 65 = ₹4,875 (ratio: 1:1.5) ✓
  Reward T2 = 150 × 65 = ₹9,750 (ratio: 1:3) ✓
  Reward T3 = 250 × 65 = ₹16,250 (ratio: 1:5) ✓
```

### Daily Loss Limit Management

```
Daily P&L: -₹5,000 → TRADING HALTS

Timeline of a ₹5,000 loss:
  • -₹1,000 = 20% used (⚠️ Warning color)
  • -₹2,500 = 50% used (🟠 Orange bar)
  • -₹3,750 = 75% used (🔴 Red bar)
  • -₹5,000 = 100% used (🛑 STOP - No new trades)

Actions if approaching limit:
  • Close profitable trades (lock in wins)
  • Skip marginal signals
  • Reduce position size
  • Or stop trading till tomorrow
```

---

## <a name="emergency"></a>8. EMERGENCY PROCEDURES

### Emergency Button (🚨 EMERGENCY EXIT)

**When to Use:**
- Something looks WRONG
- Market is crashing
- You want OUT immediately
- All positions should close

**How to Use:**
```
1. Dashboard → Bottom of screen
2. Click: 🚨 EMERGENCY EXIT - CLOSE ALL POSITIONS
3. Confirmation: "Close ALL positions?" → YES
4. Result: All open trades closed at market price
5. Outcome: Positions = 0, PnL = whatever price you closed at
```

**After Using Emergency Exit:**
```
1. Check what went wrong (review logs)
2. Verify all positions closed in Fyers
3. Rest of day: No new orders will execute
4. Next day: Systems reset, can trade again
```

### Situations & Responses

| Situation | Response | Command |
|-----------|----------|---------|
| **Position losing fast** | Wait for SL (auto-closes) | Press 🚨 if urgent |
| **System crashes** | Check DB, close manually if needed | Restart app |
| **Internet lost** | SL still works at Fyers level | Reconnect & verify |
| **Broker time-out** | Retry automatically | Check connection |
| **Daily loss hit** | Trading HALTS (automatic) | Wait till next day |
| **Extreme volatility** | Circuit breaker activates | Wait for calm |

### Disaster Recovery

**If Database Corrupts:**
```bash
# Restore backup
cp niftytrader.db.backup-2026-04-02 niftytrader.db
# Restart app
python nifty_trader/main.py
```

**If Model Crashes:**
```python
# Fallback to rule-based signals (no ML)
# App continues automatically
# Model will retrain when > 50 new labels arrive
```

**If Broker Disconnects:**
```
• Auto-reconnect attempt every 5 seconds
• Stop-loss still works at Fyers backend
• Orders already placed are safe
• Check connection when you notice
```

---

## <a name="monitoring"></a>9. MONITORING & LOGGING

### Real-Time Dashboard

**Metrics Displayed:**

```
┌─ OPEN POSITIONS ─────────────────────────┐
│ 📊 Open Trades: 1                          │
│ 💰 Daily P&L: ₹2,450 (Green = Good!)      │
│ 📈 Win Rate: 60% (6 wins, 4 losses today) │
│ ⚠️  Daily Loss: ₹550 / ₹5,000 (11% used)  │
└──────────────────────────────────────────┘

┌─ P&L PROGRESS ───────────────────────────┐
│ ███████░░░░░░░░░░░░░░░ 50% to target     │
└──────────────────────────────────────────┘

┌─ OPEN POSITIONS TABLE ──────────────────┐
│ Symbol  │ Entry   │ Current │ PnL      │
│─────────┼─────────┼─────────┼──────────│
│ NIFTY   │ 23,500  │ 23,550  │ +₹3,250  │
└──────────────────────────────────────────┘
```

### Log Files

**Location:** `logs/niftytrader_YYYYMMDD.log`

**Important Log Messages:**

```
[INFO] ✓ Live signal cleared - confidence=0.62
[CRITICAL] 🚨 STOP-LOSS TRIGGERED: NIFTY @ 23450
[INFO] ✓ Order placed successfully: order_id=1234
[ERROR] ✗ Broker order failed: rate limit exceeded
[WARNING] ⚠️  Daily loss now: ₹3,250
[CRITICAL] 🚨 EMERGENCY EXIT ACTIVATED!
[INFO] Circuit breaker triggered - ATR spike 340%
```

### Monitoring Checklist (Every 30 min)

```
□ Dashboard open
  □ No errors in status
  □ Positions showing correctly
  □ P&L updated (within last 2 min)
  
□ No unusual messages in logs
□ Broker connection still active
□ Daily loss < 80% of limit
□ Training not running (would slow system)
```

---

## <a name="faq"></a>10. FAQ & TROUBLESHOOTING

### Q: Can I disable auto stop-loss?

**A:** NO. This is non-negotiable for live trading safety.

### Q: What if I want to increase daily loss limit?

**A:** Change `MAX_DAILY_LOSS_RUPEES` in config.py. But we recommend starting at ₹5,000.

### Q: How many trades per day?

**A:** Depends on signals. Typically 4-8 trades on normal days. Max is limited by 2-position concurrent limit.

### Q: What if token expires?

**A:** Re-authenticate in Credentials tab. Or set up auto-refresh (advanced feature).

### Q: Can I trade multiple indices?

**A:** Yes - NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX all monitored. Gate limits to 2 concurrent total (not per index).

### Q: What if model F1 drops?

**A:** System retrains automatically when it reaches 50 new labeled samples. Check logs for "Retraining model".

### Q: Can I modify signal gates?

**A:** Yes, edit ADX, DI_spread, PCR thresholds in config.py. Not recommended unless you understand the impact.

### Q: What's the minimum account size?

**A:** ₹50,000 minimum. We recommend ₹1,00,000+ for 2-lot trading.

### Q: How do I close a position manually?

**A:** You shouldn't need to (auto stop-loss handles it). If you want to close: Click position in dashboard (if implemented) or use 🚨 EMERGENCY EXIT.

### Troubleshooting

**Problem: "Broker NOT authenticated"**
```
Solution:
1. Dashboard → Credentials tab
2. Click [Re-authenticate]
3. Browser opens → Login to Fyers
4. Return to app
```

**Problem: "Database FAILED - No tables"**
```
Solution:
1. Backup current DB
2. Delete niftytrader.db
3. Restart app (recreates empty)
4. Run: python nifty_trader/database/manager.py --init
```

**Problem: "Model FAILED - F1 < 0.65"**
```
Solution:
1. Wait - model auto-retrains every 50 labels
2. Check: SELECT COUNT(*) FROM trade_outcomes WHERE label NOT NULL
3. If < 50: System waits for threshold, then retrains
```

**Problem: "Daily loss limit exceeded"**
```
Solution:
1. Trading HALTS automatically (system is working correctly)
2. Review performance
3. Can reset by:
   a) Waiting till next market day (auto-reset)
   b) Or manually change MAX_DAILY_LOSS_RUPEES (not recommended)
```

---

## FINAL CHECKLIST

Before your FIRST live trade:

- [ ] Read this entire document
- [ ] Run pre-live checklist (passes)
- [ ] Paper traded for 5+ days
- [ ] Have ₹50,000+ in account
- [ ] Backup database created
- [ ] LIVE_TRADING_MODE = True in config
- [ ] AUTO_STOP_LOSS_ENABLED = True in config
- [ ] First signal arrives → Review carefully
- [ ] Confirmation dialog → Click CONFIRM
- [ ] Order placed → Monitor dashboard
- [ ] Position closes → Review resulting PnL

---

**🚀 You're Ready for Live Trading!**

Remember: Start small (1 lot), monitor closely (first 2 hours), and trust the safety systems.

Happy trading! 📈

---

**Support Contacts:**
- Logs: `logs/` folder
- Documentation: `LIVE_TRADING_RUNBOOK.md`
- Issues: Check GitHub discussions
- Emergency: Click 🚨 button
