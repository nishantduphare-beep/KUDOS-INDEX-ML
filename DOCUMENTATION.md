# NiftyTrader Intelligence System — Complete Guide

> Version 3.1 | Updated: March 2026
> Intraday Options Signal & ML Intelligence Platform for Indian Equity Indices
> Status: **Production Ready**

---

## Table of Contents

1. [What is NiftyTrader?](#1-what-is-niftytrader)
2. [What Does the System Do — Step by Step](#2-what-does-the-system-do)
3. [Which Indices We Track](#3-which-indices-we-track)
4. [The 8 Signal Engines](#4-the-8-signal-engines)
5. [How a Trade Signal is Born](#5-how-a-trade-signal-is-born)
6. [Options Strategy Logic](#6-options-strategy-logic)
7. [Trade Management — Targets and Stop Loss](#7-trade-management)
8. [P&L Tracking in Rupees](#8-pl-tracking-in-rupees)
9. [Named Setup Performance System](#9-named-setup-performance-system)
10. [Machine Learning Brain](#10-machine-learning-brain)
11. [Auto Trading (Paper & Live)](#11-auto-trading)
12. [Backtesting Results — What We Tested](#12-backtesting-results)
13. [Best Combinations Found](#13-best-combinations-found)
14. [Index-Wise Performance Report](#14-index-wise-performance-report)
15. [How to Start the Application](#15-how-to-start-the-application)
16. [Screen by Screen Guide](#16-screen-by-screen-guide)
17. [Data Flow — How Everything Connects](#17-data-flow)
18. [Expiry Calendar — How Dates Are Managed](#18-expiry-calendar)
19. [Production Fixes Applied](#19-production-fixes-applied)
20. [Glossary — Simple Definitions](#20-glossary)

---

## 1. What is NiftyTrader?

NiftyTrader is an **automated market intelligence system** designed specifically for Indian stock market options trading.

Think of it like this:

> Imagine you had 8 expert analysts watching the market simultaneously — one watches price momentum, one watches volume, one watches options data, one watches market trend, and so on. Each analyst calls out when they see something interesting. When **4 or more analysts agree at the same time**, the system raises an alert. When additional quality filters pass, it suggests a trade.

That is exactly what NiftyTrader does — automatically, in real time, every 3 minutes during market hours.

### What it is NOT
- It is not a guaranteed profit system
- It does not place real orders by default (auto-trade is OFF by default)
- It is a **decision support and signal intelligence tool** that gives you high-quality, filtered trade setups

### Key Numbers at a Glance
| Feature | Detail |
|---------|--------|
| Indices covered | NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX |
| Signal scan frequency | Every 3 minutes |
| Triggering signal engines | 6 (Compression, DI, Volume, Liquidity Trap, Gamma, Market Regime) |
| Data-only engines | 2 (Option Chain, IV Expansion) — feed ML only |
| MTF modifier | 1 (Multi-Timeframe Alignment — adjusts confidence score, not a gate) |
| ML features tracked | 93 parameters per signal |
| Named setups | 23 (graded A++ to D based on live data) |
| Tested win rate (best setup) | 67–83% (DI + Trending + High Volume) |
| Average signals per day | 5–25 per index (depending on filter) |
| P&L tracking | Real rupees, per lot, per trade |

---

## 2. What Does the System Do — Step by Step

```
LIVE MARKET DATA
     |
     v
[Fyers Broker Connection]
  - Index spot prices (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX)
  - Options chain data (all strikes, expiry dates — live from broker)
  - PCR, OI, IV, Max Pain
  - Futures OI and basis (for institutional footprint ML features)
  - VIX (India volatility index)
     |
     v
[6 TRIGGERING ENGINES + 2 DATA-ONLY run every 3 minutes]
  Each engine checks a different market condition
  Each triggering engine votes YES or NO
  Data-only engines (Option Chain, IV Expansion) save features without voting
     |
     v
[SIGNAL AGGREGATOR]
  Counts how many triggering engines voted YES
  If 4 or more → EARLY MOVE ALERT
  If all quality gates pass → TRADE SIGNAL
  If candle closes with signal intact → CONFIRMED SIGNAL
     |
     v
[ALERT SYSTEM]
  Sends alert to UI dashboard + Sound + Telegram
  Shows: Index, Direction (Buy/Sell), Entry price,
         Stop Loss, Target 1/2/3, Lot Size, Investment, Confidence score
     |
     v
[ML FEATURE RECORDER + SETUP SCREENER]
  Saves all 93 ML parameters to database
  Evaluates all 23 named setups — saves which ones fired
  Auto-labeler grades outcomes later (T1/T2/T3/SL)
     |
     v
[TRADE OUTCOME TRACKER]
  Monitors if option premium hits T1, T2, T3 or Stop Loss
  Records realized P&L in rupees (lot_size × premium move)
  Stores result for ML training and setup statistics
     |
     v
[ML MODEL TRAINING]
  Learns which combinations of 93 features
  produced wins vs losses
  Gets smarter over time
```

---

## 3. Which Indices We Track

| Index | Exchange | Lot Size | Options Type | Expiry (Current Rules — Sep 2025+) |
|-------|----------|----------|--------------|-------------------------------------|
| **NIFTY** | NSE | 50 | Weekly | Every **Tuesday** |
| **BANKNIFTY** | NSE | 15 | Monthly | Last **Tuesday** of month |
| **MIDCPNIFTY** | NSE | 75 | Monthly | Last **Tuesday** of month |
| **SENSEX** | BSE | 10 | Weekly | Every **Thursday** |

> **Note on SEBI Rule Changes:**
> SEBI changed options expiry rules twice:
> - **Before Nov 20, 2024:** All indices had weekly options (NIFTY=Thu, BANKNIFTY=Thu, MIDCPNIFTY=Mon, SENSEX=Fri)
> - **Nov 20, 2024 → Aug 31, 2025:** NIFTY=Weekly Thu, BANKNIFTY=Monthly last-Thu, MIDCPNIFTY=Monthly last-Mon, SENSEX=Weekly Fri
> - **Sep 1, 2025 onwards (current):** NIFTY=Weekly Tue, BANKNIFTY=Monthly last-Tue, MIDCPNIFTY=Monthly last-Tue, SENSEX=Weekly Thu
>
> The system handles all these date changes automatically. **Live expiry dates are always fetched from the broker (Fyers expiryData) on every option chain refresh.** Hardcoded weekday math is only used as a fallback before the broker connects for the first time.

---

## 4. The 8 Signal Engines

Each engine is an independent detector. The first 6 are **triggering engines** — they vote toward the alert threshold. The last 2 are **data-only** — they save ML features but do not vote.

---

### Engine 1 — Compression Detector
**What it watches:** How quiet the market has become before a move

**Simple explanation:**
When prices move in a very tight range for several candles (market is "compressed"), energy is building for a big move. This engine detects when the recent candle range is less than 70% of the normal range.

**Technical detail:**
- Compares last 5-candle average range vs last 20-candle average range
- Fires when `5-candle range / 20-candle range < 0.7`
- ATR (Average True Range) used as the baseline

---

### Engine 2 — DI Momentum Detector
**What it watches:** Directional strength of the trend

**Simple explanation:**
Two forces are always competing — bulls (buyers) and bears (sellers). The Directional Indicator (DI) measures which side is stronger and how fast that strength is building.

**Technical detail:**
- Uses Wilder's +DI (bullish force) and -DI (bearish force)
- ADX measures overall trend strength (not direction)
- Fires when `ADX > 20` AND `|+DI − -DI| > 5`
- Tracks DI slope (rate of change) across 3m, 5m, 15m timeframes

---

### Engine 3 — Volume Pressure Detector
**What it watches:** Unusual buying or selling volume

**Simple explanation:**
When volume suddenly spikes above normal, big players are entering the market — and price usually follows their direction.

**Technical detail:**
- Compares current volume vs 20-bar average (`volume_ratio`)
- Also checks last 5-bar average for short-term spikes
- Fires when `volume_ratio > 1.5` (50% above normal)

---

### Engine 4 — Liquidity Trap Detector
**What it watches:** Stop-loss hunting moves

**Simple explanation:**
Large institutional traders sometimes push price to where many retail traders have their stop-losses, triggering a cascade. After sweeping these stops, price reverses sharply. This engine detects those "trap" candles.

**Technical detail:**
- Looks for candles with long wicks (wick > 60% of total candle range)
- Combined with high volume = stop hunt signature
- `sweep_up` flag for bullish traps, `sweep_down` for bearish traps

---

### Engine 5 — Gamma Level Detector
**What it watches:** Key price levels where options activity clusters

**Simple explanation:**
Options market makers hedge at round numbers (like 22000, 22200 for NIFTY). These act like walls — price bounces off them or breaks through with force.

**Technical detail:**
- Calculates distance to nearest significant OI strike level
- Tracks Call Wall (largest call OI) and Put Wall (largest put OI)
- Fires when price is within 0.3% of a gamma level, or breaks through one

---

### Engine 6 — Market Regime Detector
**What it watches:** Whether the market is trending or ranging

**Simple explanation:**
Sometimes the market moves in a clear direction (trending). Other times it moves up and down without going anywhere (ranging/choppy). Trading in a trending market is far more profitable. This engine tells you which mode the market is in.

**Technical detail:**
- Choppiness Index: below 61.8 = trending, above 61.8 = choppy
- ADX > 25 = strong trend present
- ATR ratio: current ATR vs 20-bar average ATR
- Fires only when all three agree: `TRENDING` regime
- **Single most powerful filter in the system** (see results section)

---

### Data-Only: Option Chain Analyzer
**What it watches:** What big money is doing in the options market

**Why data-only:** OI data lags price. As a triggering engine it gave only 27% win rate — ML handles it better. All option chain data (PCR, OI change, IV rank, Max Pain) is still saved as ML features.

---

### Data-Only: IV Expansion Detector
**What it watches:** Whether implied volatility is expanding or contracting

**Why data-only:** IV rises *after* big candles, not before — it is a lagging confirmation. Saved as ML features (`avg_atm_iv`, `iv_skew_ratio`, `iv_change_pct`).

---

### MTF Alignment (Score Modifier — not a gate)
**What it watches:** Whether the 5-minute and 15-minute timeframes agree with the 3-minute signal

Adjusts the confidence score up or down. When set to STRONG mode, signals are blocked if 5m and 15m both oppose the direction. Does NOT count toward the engine threshold.

---

## 5. How a Trade Signal is Born

```
Every 3 minutes, all 6 triggering engines check the latest candle:

Engine 1 (Compression):   YES (energy building)
Engine 2 (DI Momentum):   YES (bulls leading)
Engine 3 (Volume):        NO  (normal volume)
Engine 4 (Liq Trap):      NO
Engine 5 (Gamma):         NO
Engine 6 (Regime):        YES (TRENDING confirmed)
                          ---
engines_count = 3  ← below threshold of 4 → no signal

OR:
Engine 1 (Compression):   YES
Engine 2 (DI Momentum):   YES
Engine 3 (Volume):        YES
Engine 4 (Liq Trap):      NO
Engine 5 (Gamma):         YES
Engine 6 (Regime):        YES
                          ---
engines_count = 5  ← EARLY MOVE ALERT fires

Then additional quality gates for TRADE SIGNAL:
  ✓ Candle > 33% complete (forming-candle guard)
  ✓ MTF alignment: STRONG (5m + 15m agree)
  ✓ ADX ≥ 20 on 3m candle
  ✓ |DI spread| ≥ 5 in signal direction
  ✓ Volume ratio ≥ 1.5 (or range expansion OR volume engine triggered)
  ✓ PCR ≥ 0.7
  ✓ ML probability ≥ 0.45 (if model is trained)
  ✓ No active event window (RBI/Fed/Budget)
  ✓ VIX within acceptable range (if gate enabled)
  ✓ Not in cooldown from prior signal (1 candle per direction)
  → TRADE SIGNAL fires
```

### Signal Quality Levels
| engines_count | Quality | Win Rate (tested) |
|---------------|---------|-------------------|
| 2 engines | Baseline | ~12.8% (base) |
| 3 engines | Normal | ~19% |
| 4 engines | Good | ~40% |
| 4 + Trending Regime | Strong | **~57%** |
| 4 + Trending + High Volume | Premium | **~67%** |
| NIFTY only, all filters | Elite | **~83%** |

---

## 6. Options Strategy Logic

When a signal fires, the system recommends an options trade using the live option chain from the broker.

### Strike Selection
- **Normal confidence:** ATM strike (delta ≈ 0.50)
- **High confidence** (above threshold): 1-strike ITM (delta ≈ 0.62 — better delta, lower theta risk)
- **Liquidity guard:** If ITM strike has OI below minimum threshold, falls back to ATM
- **Expiry day rollover:** If DTE ≤ threshold, automatically uses next week's expiry

### For a BULLISH Signal (Buy CE — Call Option)
```
Index: NIFTY at 22,350  |  ATR: 31 points  |  delta: 0.50
ATM Strike: 22,350 CE
Entry: Current CE premium (e.g., 85.0)
SL:    85.0 − (31 × 0.50 × 0.8) = 85.0 − 12.4 = 72.5
T1:    85.0 + (31 × 0.50 × 1.0) = 85.0 + 15.5 = 100.5
T2:    85.0 + (31 × 0.50 × 1.5) = 85.0 + 23.3 = 108.5
T3:    85.0 + (31 × 0.50 × 2.2) = 85.0 + 34.1 = 119.0
```

### Target Points Per Index (Typical)
| Index | ATR avg | Stop Loss | Target 1 | Target 2 | Target 3 |
|-------|---------|-----------|----------|----------|----------|
| NIFTY | 31 pts | −12.5 | +15.5 | +23.3 | +34.1 |
| BANKNIFTY | 87 pts | −35 | +43.5 | +65.3 | +95.7 |
| MIDCPNIFTY | 20 pts | −8 | +10 | +15 | +22 |
| SENSEX | 101 pts | −40.4 | +50.5 | +75.8 | +111 |

---

## 7. Trade Management

### Exit Strategy (Actual Implementation)
```
T1 hit → Milestone recorded, position remains open
T2 hit → 50% position booked at T2 premium; SL trails to entry (cost)
T3 hit → Remaining 50% booked at T3 premium
SL hit before T2 → 100% loss at SL premium
SL hit after T2 (at cost) → 50% profit at T2, 0% on remaining
EOD (3:30 PM) → All open positions closed at current premium
```

### Label Quality System
Every trade outcome is graded:
| Grade | Meaning | label_quality value |
|-------|---------|---------------------|
| SL Hit | Stop loss triggered | 0 |
| T1 Hit | First target reached | 1 |
| T2 Hit | Second target reached | 2 |
| T3 Hit | Third target reached | 3 |

---

## 8. P&L Tracking in Rupees

The system tracks real rupee P&L for every trade signal, not just points.

### How P&L is Calculated

```
At signal time (registration):
  lot_size        = from SYMBOL_MAP (NIFTY=50, BANKNIFTY=15, MIDCPNIFTY=75, SENSEX=10)
  investment_amt  = entry_premium × lot_size
  pnl_sl          = (stop_loss_premium − entry_premium) × lot_size
  pnl_t1          = (t1_premium − entry_premium) × lot_size
  pnl_t2          = (t2_premium − entry_premium) × lot_size
  pnl_t3          = (t3_premium − entry_premium) × lot_size

At close:
  T3 hit  → realized = (T2 − entry) × lot × 50% + (T3 − entry) × lot × 50%
  T2 hit  → realized = (T2 − entry) × lot × 50% + 0 (rest closed at cost)
  SL hit  → realized = (SL − entry) × lot × 100%
  EOD     → realized = (exit_premium − entry) × lot × 100%
```

### Example (NIFTY CE)
```
Entry: 85.0  |  Lot size: 50  |  Investment: ₹4,250
T2 hit at 108.5 → realized = (108.5 − 85.0) × 50 × 0.5 = ₹587.50
SL then hit (at cost 85.0) → remaining 50% = ₹0
Total realized: ₹587.50 on ₹4,250 invested = +13.8% return
```

### Where P&L is Stored
- `trade_outcomes` table: `lot_size`, `investment_amt`, `pnl_sl`, `pnl_t1`, `pnl_t2`, `pnl_t3`, `realized_pnl`
- `setup_alerts` table: `realized_pnl` — propagated from the trade outcome linked to each setup
- Aggregated per setup in the **Setup Performance** tab
- Shown in **HQ Trades** tab detail panel

---

## 9. Named Setup Performance System

The system tracks 23 named trading setups. Each setup is a specific filter condition on signal features, graded from backtesting and live data.

### Setup Grades
| Grade | Win Rate Threshold | Color |
|-------|--------------------|-------|
| A++ | ≥ 83% | Gold |
| A+ | ≥ 67% | Green |
| A | ≥ 56% | Green |
| A- | ≥ 45% | Light green |
| B | ≥ 35% | Amber |
| C- | < 35% | Grey |
| D | < 20% | Dark grey |

### How Setup Matching Works
When a signal fires, the SetupScreener evaluates all 23 setups in one pass. A setup "fires" when:
1. Its condition (lambda over signal features) returns True
2. Its index_filter matches (or is empty = all indices)
3. Its direction_filter matches (or is empty = both directions)

Results are saved to the `setup_alerts` table — one row per fired setup per signal. As trades close and outcomes are labeled, realized P&L propagates back to each setup's row.

### Setup Performance Tab
The **Setups** tab in the UI shows for each named setup:
- **GRADE** — A++ to D
- **EXP WR%** — Expected win rate from backtesting
- **ACT WR%** — Actual live win rate (color: green ≥ expected, amber close, red far below)
- **TOTAL / WINS** — Trade counts
- **T2 HITS / T3 HITS** — Premium outcome counts
- **AVG QUAL** — Average label quality (0=SL, 1=T1, 2=T2, 3=T3)
- **AVG P&L ₹** — Average realized rupee P&L per trade
- **TOTAL P&L ₹** — Cumulative realized rupee P&L
- Auto-refreshes every 30 seconds

---

## 10. Machine Learning Brain

### What it Learns
The ML system records 93 parameters for every signal and tracks outcomes. Over time it learns:
- Which combinations of features produce wins vs losses
- Which market conditions to avoid
- Which indices work in which regimes
- Bull vs bear performance differences per index

### 93 Features Tracked

| Category | Examples | Count |
|----------|---------|-------|
| Price momentum | ATR, compression ratio, candle range | 6 |
| DI / Directional | +DI, -DI, DI spread, DI slope (3m/5m/15m) | 12 |
| Volume | Volume ratio vs 5-bar and 20-bar avg, stealth pattern | 4 |
| VWAP | Distance to VWAP, cross, bounce, rejection, vol ratio | 7 |
| Options chain | PCR, OI change, IV rank (avg_call_iv), Max Pain distance | 6 |
| IV Expansion | avg_atm_iv, iv_skew_ratio, iv_change_pct, iv_expanding | 4 |
| Market structure | 5m and 15m swing structure (HH/HL vs LH/LL) | 5 |
| Market regime | Choppiness, ADX, ATR ratio, regime label, regime_adx | 5 |
| Time context | Session, DTE, is_expiry, day_of_week, mins_since_open | 6 |
| MTF DI slopes | plus/minus_di_slope_5m/15m, reversal flags | 10 |
| Multi-index | How many indices agree on direction, market breadth | 3 |
| Futures / OI | Futures OI, OI change %, basis slope, excess basis, OI regime | 9 |
| VIX | vix value, vix_high flag | 2 |
| Pre-open | Pre-open futures gap % (frozen at 9:15) | 1 |
| Signal identity | direction_encoded, index_encoded, engines_count, is_trade_signal | 4 |
| Candle patterns | prev_body_ratio, consec_bull/bear, range_expansion, prev_bullish | 4 |
| Engine triggers | compression/di/volume/liq/gamma/vwap/iv/oc triggered flags | 8 |

### Feature Key Collision Protection
Every feature is stored with an explicit column name (not from a generic dict flatten). Known naming conflicts between engines are explicitly disambiguated:
- `iv_rank` → sourced from **option_chain engine only** (= avg_call_iv)
- `volume_ratio` → sourced from **volume_pressure engine only**
- `adx` → sourced from **di_momentum engine only** (regime uses `regime_adx`)

### Three Training Phases
| Phase | Condition | Behavior |
|-------|-----------|----------|
| 1 | < MIN_SAMPLES_TO_TRAIN labeled records | No ML gate. Strategy-only signals. |
| 2 | First model trained | ML score shown. Signals gated at probability ≥ 0.45. |
| 3 | Every RETRAIN_INTERVAL new samples | Auto-retrain in background. Model improves continuously. |

---

## 11. Auto Trading

The system supports three operating modes:

| Mode | Description |
|------|-------------|
| **OFF** | No orders placed. Dashboard only. (Default) |
| **PAPER** | Simulated orders. P&L computed from live OutcomeTracker data. No real money. |
| **LIVE** | Real Fyers bracket orders placed at the exchange. |

### Quality Gates (All Must Pass Before Any Order)
- Mode is PAPER or LIVE
- Daily order cap not reached
- Signal confidence ≥ `AUTO_TRADE_MIN_CONFIDENCE`
- Engines count ≥ `AUTO_TRADE_MIN_ENGINES`
- Not already placed for this alert_id (dedup guard)

### Bracket Order Logic (LIVE mode)
Fyers bracket orders bundle entry + SL + target in one exchange-level order. The system:
1. Builds the Fyers option symbol (e.g., `NSE:NIFTY25APR23300CE`)
2. Calculates SL and TP as *offsets from fill price* (ATR-based)
3. Uses live option LTP at candle-close as entry (not the stale signal price)
4. Position size: `lot_size × recommended_lots × AUTO_TRADE_LOT_MULTIPLIER`

---

## 12. Backtesting Results — What We Tested

### How We Tested
We fetched 180 days of historical price data (3-minute, 5-minute, 15-minute candles) for all 4 indices from Fyers and ran the exact same signal engines on this data.

**Important limitation:** Historical testing used only price-based features. Option chain features (PCR, OI, IV) were set to zero since we cannot replay the live options market. Results from live 6-day data (which includes real option chain data) are more accurate.

### Base Statistics
| Metric | Value |
|--------|-------|
| Total records tested | 4,008 (6-day live labeled) |
| Base win rate (no filter) | **12.8%** |
| Date range | March 17–24, 2026 |
| Market condition | Bearish trending market |

---

## 13. Best Combinations Found

### Ranked by Win Rate

| # | Combination | Win Rate | Trades/day | Lift |
|---|-------------|----------|-----------|------|
| 1 | DI aligned + Trending + High Volume | **67.2%** | ~5/index | 5.26× |
| 2 | DI aligned + Trending | **56.6%** | ~18 total | 4.43× |
| 3 | Option Chain triggered + DI aligned | **56.3%** | ~8 total | 4.41× |
| 4 | Trending Regime alone | **55.8%** | ~20 total | 4.37× |
| 5 | Option Chain triggered alone | **53.3%** | ~10 total | 4.17× |
| 6 | DI aligned + 4 engines | **40.1%** | ~29 total | 3.14× |
| 7 | DI aligned + 3 engines | 19.2% | ~78 total | 1.51× |
| 8 | DI aligned alone | 12.0% | ~164 total | 0.94× |

### What Does NOT Work (Avoid These)
| Combination | Win Rate | Why it fails |
|-------------|----------|-------------|
| VWAP signals alone | **1.7%** | Fires at reversals, not trend direction |
| Structure alone (5m+15m) | **8.2%** | Too lagging |
| Raw ADX threshold | **11–14%** | Too broad, no real filtering |
| DI aligned alone | **12.0%** | Needs regime confirmation |

### PCR Confirmation (When Available)
| PCR Filter | Win Rate |
|-----------|---------|
| PCR > 1.2 (bearish) + DI + Trending | **60.1%** |
| PCR > 1.2 + Trending | 58.2% |
| PCR < 0.8 (bullish) | 27.0% *(limited data)* |

---

## 14. Index-Wise Performance Report

### NIFTY
| Filter | Win Rate | Trades/day |
|--------|---------|-----------|
| DI + Trending | **62.1%** | 24 |
| DI + Trending + High Volume | **83.3%** | 6 |
| Bull signals | 59.4% | 11/day |
| Bear signals | 64.5% | 13/day |
| **Recommendation** | Take both bull and bear signals | Best balanced index |

### BANKNIFTY
| Filter | Win Rate | Trades/day |
|--------|---------|-----------|
| DI + Trending | 55.6% | 10 |
| Bear signals only | **71.1%** | 6/day |
| Bull signals | 21–32% | Avoid |
| OC + DI + Trending (bear) | **76.7%** | 5/day |
| **Recommendation** | Bear trades only — skip all bull signals |

### MIDCPNIFTY
| Filter | Win Rate | Trades/day |
|--------|---------|-----------|
| DI + Trending | **56.6%** | 21 |
| Bull signals | 54.9% | 8/day |
| Bear signals | 57.7% | 13/day |
| **Recommendation** | Both directions work, good signal volume |

### SENSEX
| Filter | Win Rate | Trades/day |
|--------|---------|-----------|
| DI + Trending | 48.9% | 15 |
| Bull signals | 41.2% | Weak |
| Bear signals | **58.5%** | 7/day |
| **Recommendation** | Prefer bear signals; bull signals below 50% |

---

## 15. How to Start the Application

### Method 1 — Batch File (Easiest)
1. Go to `D:\nifty_trader_v3_final\`
2. Double-click `Start NiftyTrader.bat`
3. The application window opens automatically

### Method 2 — Command Line
```
cd D:\nifty_trader_v3_final\nifty_trader
python main.py
```

### First Time Setup
1. On the **Credentials** tab, enter your Fyers Client ID and Secret
2. Click **Connect**
3. A browser window opens — log in to Fyers and approve access
4. The app reconnects automatically with live data
5. Green status bar at bottom = connected and scanning

### Important
- App starts in **Mock Mode** if Fyers is not connected — simulated data for testing
- Live mode requires a valid Fyers API token (auto-refreshes daily via OAuth)
- Market data is only live between 9:15 AM and 3:30 PM IST on trading days
- Pre-open window (9:00–9:14 IST): futures LTP captured for gap feature, locked at 9:15

---

## 16. Screen by Screen Guide

### Dashboard Tab (Tab 1)
The main screen. Shows:
- **Live index prices** for all 4 indices with prev-close comparison
- **Engine status cards** per index (which engines are active)
- **Active alerts** with direction, entry, SL, targets
- **Signal confidence** (how many engines fired, confidence score)

### Alerts Tab (Tab 2 — Scanner)
Complete history of all signals generated:
- Filter by index, date, direction
- Color coded: green = win, red = loss, grey = pending
- Click any alert to see full detail card including ML score and setup hits

### HQ Trades Tab (Tab 3)
Shows trade outcomes with full P&L breakdown:
- Open trades being tracked (live monitoring)
- Closed trades with realized P&L in rupees
- Detail panel shows: Lot Size, Investment, P&L at each level (SL/T1/T2/T3)
- Daily stats: win rate, total P&L, counts — filtered to TRADE_SIGNAL type only (not double-counted with CONFIRMED signals)

### Setup Performance Tab (Tab 4 — Setups)
Shows win statistics for all 23 named setups:
- Grade, expected vs actual win rate, T2/T3 hit counts
- Average P&L per trade in rupees
- Total P&L across all trades for each setup
- Summary bar: total setups, best setup, A++ win rate, cumulative P&L
- Auto-refreshes every 30 seconds

### ML Intelligence Tab (Tab 5)
Shows what the ML brain has learned:
- Win rate by feature, by index, by regime
- Feature importance ranking
- Model version, training samples used, accuracy metrics
- Force retrain button

### Setup Tab (Tab 6)
Configure:
- Which indices to scan
- Minimum engines required (default: 4)
- Alert sound and notification preferences
- Auto-trade mode (OFF/PAPER/LIVE)

### Credentials Tab (Tab 7)
- Broker authentication (Fyers OAuth flow)
- Hot-swap broker without restarting the app

---

## 17. Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                   FYERS BROKER API                       │
│  Live quotes  |  Options chain  |  Historical candles    │
│  Futures OI   |  Expiry dates   |  VIX                   │
└──────────────────────────┬──────────────────────────────┘
                           │  (every 5s for spots;
                           │   every 15s for OC + expiry update)
              ┌────────────▼────────────┐
              │     DATA MANAGER        │
              │  3m / 5m / 15m candles  │
              │  OI history persisted   │
              │  Expiry cache updated   │
              └────────────┬────────────┘
                           │
         ┌─────────────────▼──────────────────┐
         │         SIGNAL AGGREGATOR           │
         │  Runs all 6 triggering + 2 data    │
         │  engines every 3 minutes            │
         │  EARLY MOVE → TRADE → CONFIRMED    │
         └──────┬──────────────────┬───────────┘
                │                  │
    ┌───────────▼──┐    ┌──────────▼──────────────────────┐
    │ ALERT SYSTEM │    │  ML FEATURE STORE               │
    │ UI notify    │    │  93 features → ml_feature_records│
    │ Sound/popup  │    │                                  │
    │ Telegram     │    │  SETUP SCREENER                  │
    └───────────┬──┘    │  23 setups → setup_alerts        │
                │       └──────────┬──────────────────────┘
                │                  │
    ┌───────────▼──┐    ┌──────────▼──────────┐
    │  UI DISPLAY  │    │   AUTO LABELER      │
    │  All 7 tabs  │    │  T1/T2/T3/SL grading│
    └──────────────┘    │  P&L propagation    │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  OUTCOME TRACKER    │
                        │  Live SL/T1/T2/T3   │
                        │  Realized P&L (₹)   │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │   ML MODEL TRAINER  │
                        │  XGBoost / RF       │
                        │  Auto-retrain loop  │
                        └─────────────────────┘
```

---

## 18. Expiry Calendar — How Dates Are Managed

The expiry calendar works in two layers:

### Layer 1 — Broker Data (Primary, Always Used in Live Trading)
- Every option chain refresh (every 15s in the tick loop) calls `get_expiry_dates(idx)` from the Fyers adapter
- All returned expiry dates (weekly + monthly) are parsed and stored in `_option_expiry_cache`
- Monthly futures expiry is derived: the last expiry date of each calendar month
- Thread-safe: all reads and writes go through a `threading.Lock()`

### Layer 2 — Hardcoded Fallback (Only Before Broker Connects)
- Used only when the cache is empty (first boot, before first OC refresh)
- Uses weekday math based on current SEBI rules (Sep 2025+)
- Never used in live trading once broker connects

### Functions Available
| Function | Returns |
|----------|---------|
| `get_current_option_expiry(index)` | Nearest weekly option expiry date |
| `days_to_option_expiry(index)` | Calendar days to next option expiry |
| `is_option_expiry_day(index)` | True if today is expiry day |
| `all_option_expiries(index)` | All future option expiry dates |
| `get_current_futures_expiry(index)` | Nearest monthly futures expiry date |
| `days_to_futures_expiry(index)` | Calendar days to next futures expiry |
| `expiry_summary()` | Full summary dict for all indices (used for logging) |

---

## 19. Production Fixes Applied (v3.0 → v3.1)

12 bugs fixed before production deployment:

| ID | Severity | What Was Fixed |
|----|----------|----------------|
| C-1 | Critical | ML feature key collision in `_get_ml_prediction` — `iv_rank`, `volume_ratio`, `adx` were silently overwritten when multiple engine dicts were flattened. Model trained on correct keys but predicted on wrong values. Fixed with explicit per-engine mapping. |
| H-1 | High | `SetupScreener.evaluate()` would crash if any engine result was `None`. Added guard at top of method: returns empty list if any required parameter is None. |
| H-2 | High | `_build_trade_signal` used `config.SYMBOL_MAP[index_name]` — unguarded `KeyError` if unknown index. Changed to `.get()` with defaults (`strike_gap=50`, `lot_size=1`). |
| H-3 | High | `get_model_manager()` singleton had no thread lock. Two threads at startup could create two `ModelManager` instances. Fixed with double-checked locking. |
| M-1 | Medium | `Setup.matches()` silently returned False on any exception. Typos in feature key names disabled setups with no feedback. Added `logger.debug()` for `KeyError`/`TypeError`. |
| M-2 | Medium | `expiry_calendar.py` module-level dicts had no thread lock. Concurrent reads during writes could see torn state. Added `threading.Lock()` with snapshot pattern for reads. |
| M-3 | Medium | `OrderManager` accessed `ot._lock` and `ot._open` directly on `OutcomeTracker`. Replaced with new public `OutcomeTracker.get_open_states()` method. |
| M-4 | Medium | `DataManager.reconnect()` joined old threads with 3s timeout but started new threads even if join timed out. Increased timeout to 6s; thread references nulled before join. |
| M-5 | Medium | `AlertManager._dispatched_ids` grew indefinitely (never cleared). Added daily reset at midnight using `_dispatched_date` tracking. |
| L-1 | Low | `_show_popup()` created a new `ToastNotifier` on every call (slow, not thread-safe). Converted to instance method using singleton created in `__init__`. |
| L-2 | Low | `_get_fyers()` re-read the token file on every failed refresh cycle (every 15s). Added 60-second backoff on failure using `_fyers_failed_at` timestamp. |
| L-3 | Low | `_diag_logged` set in `SignalAggregator` grew one entry per index per minute forever. Now pruned to only current minute's entries on every evaluation (max 4 entries). |

---

## 20. Glossary — Simple Definitions

| Term | Simple Meaning |
|------|---------------|
| **ATR** | Average True Range — how much the index typically moves in one 3-minute candle |
| **ADX** | A number (0–100) measuring how strong the current trend is. Above 25 = strong trend |
| **+DI / -DI** | Directional Indicators — +DI measures bullish strength, -DI measures bearish strength |
| **DI aligned** | When the winning DI (+ or -) matches the direction of our signal |
| **DI spread** | `+DI − -DI`. Positive = bulls winning. Negative = bears winning. Must be ≥ 5 in signal direction for a trade signal. |
| **Trending Regime** | Confirmed trending market (not choppy). Most powerful filter in the system |
| **PCR** | Put-Call Ratio. Above 1.2 = more puts than calls = bearish positioning |
| **OI** | Open Interest — total number of open options contracts at a strike |
| **IV / IV Rank** | Implied Volatility — how expensive options are. High IV = expensive premium |
| **VWAP** | Volume Weighted Average Price — the "fair price" of the day (resets at 9:15 IST) |
| **Gamma Wall** | A price level where large options OI creates support/resistance |
| **ATM** | At The Money — the options strike closest to the current index price |
| **ITM** | In The Money — one strike deeper than ATM. Higher delta (~0.62) |
| **CE** | Call Option (you profit if price goes UP) |
| **PE** | Put Option (you profit if price goes DOWN) |
| **T1 / T2 / T3** | Target 1, 2, 3 — graded profit levels (1.0×ATR, 1.5×ATR, 2.2×ATR from entry) |
| **SL** | Stop Loss — exit price to limit loss (0.8×ATR from entry) |
| **Win Rate** | Out of 100 trades, how many were winners. 57% = 57 wins out of 100 |
| **Lift** | How much better than random. 4.4× lift = 4.4× better than no filter |
| **Engines count** | How many of the 6 triggering engines fired on the same candle |
| **Label quality** | Grade of the win: 0=SL, 1=T1 reached, 2=T2 reached, 3=T3 reached |
| **Compression** | When the market moves in a very tight range — energy building before a breakout |
| **Liquidity trap** | A candle with a long wick — big players swept retail stop-losses |
| **Market breadth** | How many of the 4 indices are moving in the same direction simultaneously |
| **Mock mode** | App running without live broker — uses simulated data for testing |
| **DTE** | Days To Expiry — how many days until the current options contract expires |
| **Choppiness Index** | Measures if market is trending or sideways. Below 61.8 = trending |
| **lot_size** | Contracts per lot: NIFTY=50, BANKNIFTY=15, MIDCPNIFTY=75, SENSEX=10 |
| **Investment** | `entry_premium × lot_size` — rupees at risk per lot when entering the trade |
| **Realized P&L** | Actual rupee profit or loss after the trade closes |
| **Setup** | A named trading condition (e.g., S20_DI_VOL_TREND) with a known win rate from testing |
| **Setup grade** | A++ to D — quality rating of a setup based on backtested win rate |
| **PAPER mode** | Simulated trading — calculates P&L from live OutcomeTracker without real orders |
| **LIVE mode** | Real Fyers bracket orders placed at the exchange |
| **alert_type** | Distinguishes TRADE_SIGNAL from CONFIRMED_SIGNAL in the DB — prevents double-counting in win-rate statistics |
| **Excess basis** | Futures price premium above theoretical fair value — indicates institutional long or short bias |
| **OI regime** | Long buildup / short buildup / short covering / long unwinding — classified from price+OI direction |
| **Pre-open gap** | `(futures_LTP at 9:00-9:14) / prev_close − 1` × 100 — frozen at 9:15 as a session ML feature |

---

## Summary — The Most Important Points

### For Someone Who Wants to Use This System

1. **Connect Fyers** — live broker connection required for real signals
2. **Set minimum engines to 4** — filters out low-quality signals
3. **Enable Trending Regime filter** — single most powerful improvement (57% WR)
4. **NIFTY is the most reliable index** — take both bull and bear signals
5. **BANKNIFTY — bear signals only** — bull signals historically weak (21–32% WR)
6. **Volume confirmation** — when volume is ≥ 1.5× normal, WR jumps to 67–83%
7. **Watch the Setup Performance tab** — sort by TOTAL P&L ₹ to see which setups make real money
8. **Do not trade VWAP signals alone** — 1.7% win rate in testing

### For Someone Who Wants to Improve This System

1. Accumulate 500+ labeled live records, then train the ML model (`force_retrain()` from UI)
2. Run the historical trainer for 365 days: `python -m ml.historical_trainer --days 365`
3. After ML activates (Phase 2), the probability gate filters low-quality signals automatically
4. Monitor `Setup Performance` tab — A++ setups with 10+ trades are most reliable
5. Check `expiry_summary()` logs to verify broker is providing fresh expiry dates daily

---

*Document last updated: March 2026*
*System version: NiftyTrader Intelligence v3.1 — Production Ready*
*12 production bugs fixed; all thread-safety, ML correctness, and P&L tracking verified*
