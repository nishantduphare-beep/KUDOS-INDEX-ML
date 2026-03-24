# NiftyTrader Intelligence — Complete Documentation

> Version 3.0 | Multi-broker intraday signal engine for Indian equity indices

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Installation & Setup](#3-installation--setup)
4. [Broker Authentication (Fyers)](#4-broker-authentication-fyers)
5. [Signal Engines](#5-signal-engines)
6. [Alert System](#6-alert-system)
7. [UI Tabs Reference](#7-ui-tabs-reference)
8. [Database Schema](#8-database-schema)
9. [ML Pipeline](#9-ml-pipeline)
10. [Configuration Reference](#10-configuration-reference)
11. [Data Flow](#11-data-flow)
12. [File Structure](#12-file-structure)
13. [Outcome Tracking](#13-outcome-tracking)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Overview

**NiftyTrader Intelligence** is a real-time options trading signal engine for Indian equity indices (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX). It runs 7 independent signal engines every 3-minute candle, aggregates their votes into confidence-scored alerts, and tracks trade outcomes to continuously improve via machine learning.

### What it does

| Capability | Detail |
|---|---|
| **Market coverage** | NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX |
| **Signal timeframe** | 3-minute primary candles + 5-min / 15-min multi-timeframe validation |
| **Alert types** | Early Move Alert (4+ engines) → Trade Signal (confirmed on candle close) |
| **Brokers supported** | Fyers (primary), Dhan, Kite, Upstox, Mock (demo) |
| **Alert channels** | In-app UI, desktop popup, sound beep, Telegram |
| **ML scoring** | RandomForest/XGBoost model trained on historical outcomes; probability score augments every alert |
| **Outcome tracking** | Automated SL/T1/T2/T3 level hit detection, MFE/MAE, post-close analysis |

### Signal philosophy

- **7 triggering engines** vote on direction — no single indicator can fire a signal
- **2 data-only engines** (Option Chain, IV Expansion) still run every tick but feed ML only
- **4-engine threshold** for Early Move Alert (heads-up, high noise tolerance)
- **Candle-close confirmation** — Trade Signal waits for the next candle open before firing
- **Multi-timeframe blocking** — if 5-min AND 15-min both oppose the 3-min signal, Trade Signal is suppressed
- **Quality gates** — ADX ≥ 20, |DI spread| ≥ 5, volume ≥ 0.8× avg, PCR ≥ 0.7, MTF STRONG required

---

## 2. Architecture

### Layer diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Broker API  (Fyers / Dhan / Kite / Upstox / Mock)              │
│  REST + WebSocket                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ OHLCV, OI, Option Chain
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  DataManager  (data/data_manager.py)                            │
│  ├─ IndexState per index (spot, candles, futures, option chain) │
│  ├─ 5s tick thread — fetch spot + candle + OI                  │
│  ├─ Candle-close thread — detect 3-min boundary                │
│  └─ Indicator computation — ATR, DI, ADX, Volume SMA           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ pandas DataFrames (df, df_5m, df_15m, futures_df)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  SignalAggregator  (engines/signal_aggregator.py)               │
│  ├─ Engine 1: Compression       ├─ Engine 5: Liquidity Trap    │
│  ├─ Engine 2: DI Momentum       ├─ Engine 6: Gamma Levels      │
│  ├─ Engine 3: Volume Pressure   ├─ Engine 7: VWAP Pressure     │
│  ├─ Engine 4: Market Regime     └─ (+ 2 data-only: OC, IV)    │
│  └─ MTF Alignment (confidence modifier, not gate)              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ EarlyMoveAlert / TradeSignal
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  AlertManager  (alerts/alert_manager.py)                        │
│  ├─ UI callback → Alerts Tab                                    │
│  ├─ Sound beep (1 / 3 beeps)                                   │
│  ├─ Desktop popup (plyer)                                       │
│  └─ Telegram (optional)                                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼──────────────────────┐
          ▼                ▼                      ▼
┌──────────────┐  ┌───────────────┐   ┌───────────────────────┐
│  UI (PySide6)│  │  OutcomeTrack │   │  ML Pipeline          │
│  6 tabs      │  │  SL/T1/T2/T3  │   │  Feature Store (79+)  │
│              │  │  MFE/MAE      │   │  AutoLabeler (15 min) │
│              │  │  Post-close   │   │  RF/XGBoost model     │
└──────────────┘  └───────┬───────┘   └──────────┬────────────┘
                          │                       │
                          └──────────┬────────────┘
                                     ▼
                          ┌──────────────────────┐
                          │  SQLite Database      │
                          │  6 tables             │
                          └──────────────────────┘
```

### Key design patterns

| Pattern | Where used | Why |
|---|---|---|
| **Adapter** | `data/adapters/` | Swap brokers without changing engine logic |
| **Observer** | DataManager → SignalAggregator callbacks | Decouple data fetch from signal logic |
| **Repository** | `database/manager.py` | Clean separation of storage from business logic |
| **State Machine** | `OutcomeTracker` | OPEN → CLOSED → POST-CLOSE with clear transitions |
| **Thread Safety** | `threading.Lock` on IndexState, SignalAggregator, OutcomeTracker | Prevent race conditions in 5s tick loop |

---

## 3. Installation & Setup

### Requirements

```
Python 3.10+
PySide6
pandas, numpy
sqlalchemy
xgboost
fyers-apiv3
plyer          (desktop notifications)
```

### First run

```bash
cd nifty_trader
pip install -r requirements.txt
python main.py
```

The app will open with the **Credentials** tab active. Select your broker and authenticate.

### Mock mode (no broker needed)

Set `BROKER=mock` in environment or select **Mock** in the Credentials tab. The mock adapter generates synthetic OHLCV using geometric Brownian motion — useful for testing the UI and signal logic.

### Directory structure created on first run

```
auth/
  fyers_token.json          — Fyers access token (midnight IST expiry)
logs/
  niftytrader_YYYYMMDD.log  — daily log file
models/
  xgb_signal_v1.json        — trained XGBoost model (created after 100+ alerts)
nifty_trader.db             — SQLite database
user_settings.json          — sensitivity slider persistence
```

---

## 4. Broker Authentication (Fyers)

Fyers uses OAuth2. The flow happens inside the **Credentials** tab.

### Step-by-step

1. Enter your **App ID** (e.g. `XB12345-100`) and **Secret Key**
2. Click **Generate Auth URL** → browser opens Fyers login page
3. Log in at Fyers and authorize the app
4. Browser redirects to `https://trade.fyers.in/api-login/redirect-uri/index.html?auth_code=XXXX`
5. Copy the `auth_code=XXXX` value from the URL
6. Paste it into the **Auth Code** field in the app
7. Click **Exchange Code** → token saved to `auth/fyers_token.json`

### Token lifecycle

- Valid until **midnight IST** on the same calendar day
- On next launch: token auto-loaded if still valid (> 5 min remaining)
- If expired: the Credentials tab shows "Token expired" — repeat steps 2–7

### Alternative: Direct token paste

If you already have an access token, use **Set Token Direct** to paste it without going through the full OAuth flow.

---

## 5. Signal Engines

Each engine evaluates the latest candle data and votes BULLISH, BEARISH, or NEUTRAL. A minimum of 2-out-of-3 internal sub-conditions must pass for most engines to trigger.

---

### Engine 1 — Compression

**What it detects:** Volatility coiling before an expansion move.

| Sub-condition | Formula | Threshold |
|---|---|---|
| Range ratio | Recent 5-candle range ÷ 20-candle average range | < 0.70 |
| ATR declining | Last 3 ATR values trending down | 2 of last 3 falling |
| Volatility contraction | Close-price std (recent) ÷ close-price std (prior) | < 0.85 |

**Direction:** Always NEUTRAL — compression itself has no direction. It becomes directional only when a breakout engine confirms.

**Breakout check:** If close moves > 1×ATR beyond the compression range high/low, a breakout is flagged (used by the aggregator to gate Trade Signals).

---

### Engine 2 — DI Momentum

**What it detects:** Directional pressure before ADX confirms a crossover (leading indicator).

| Sub-condition | Formula | Threshold |
|---|---|---|
| Primary DI trending | +DI rising (bullish) or -DI falling (bearish) over last 3 candles | Slope positive |
| Secondary DI falling | Opposing DI declining | Slope negative |
| Spread widening | +DI − -DI change | ≥ 2.0 points or ≥ 15% of current spread |

**Direction:** BULLISH when +DI > -DI, BEARISH when -DI > +DI.

---

### Engine 3 — Option Chain *(Data-Only — not a triggering engine)*

**Status:** Runs every tick but does **not** count toward the 4-engine trigger threshold. Its data (PCR, max pain, OI change, iv_rank) is saved to the ML feature store for the model to learn from.

**Why demoted:** OI data confirms moves that already happened. Historical data showed 27% WR when Option Chain was the deciding engine — below breakeven for options trading.

**Data still collected for ML:**
- PCR, max pain distance, call/put OI change
- iv_rank, avg_atm_iv (used by IV Expansion engine below)

---

### Engine 4 — Volume Pressure

**What it detects:** Institutional accumulation or distribution via volume pattern.

| Sub-condition | Formula | Threshold |
|---|---|---|
| Volume spike (mandatory) | Current volume ÷ SMA-20 volume | ≥ 1.5× |
| Stealth/absorption | Small candle body on high volume (institutions absorbing) | Body < 50% of range on spike |
| Volume trend up | Last 5 candles volume ratio rising | Positive slope |

**Note:** The volume spike sub-condition is **mandatory** — the engine cannot trigger without it. However, for cash indices (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX), Fyers returns near-zero spot volume. To work around this, the signal aggregator relaxes the gate to also accept `vol_triggered OR range_ok` for index signals.

---

### Engine 5 — Liquidity Trap

**What it detects:** Stop-hunt false breakout followed by reversal (wick rejection).

| Sub-condition | Formula | Threshold |
|---|---|---|
| Sweep | Current candle high > prior 10-candle swing high (bearish trap) or low < swing low (bullish) | New extreme vs lookback |
| Wick ratio | Wick length ÷ candle range | ≥ 0.50 (50%) |
| Reversal confirmed | Close back inside the prior swing range | Close recaptured |

**Direction:** BULLISH when a sweep of lows reverses upward; BEARISH when a sweep of highs reverses downward.

---

### Engine 6 — Gamma Levels

**What it detects:** Market-maker delta hedging walls (gamma support/resistance) and gamma flips.

| Sub-condition | What it measures | Threshold |
|---|---|---|
| Near put wall | Spot price proximity to max put OI strike (support) | Within 0.2% of spot |
| Near call wall | Spot price proximity to max call OI strike (resistance) | Within 0.2% of spot |
| Gamma flip | Spot crossed the gamma wall since last snapshot | Direction of cross |

**Direction:** BULLISH near put wall or bullish gamma flip; BEARISH near call wall or bearish gamma flip.

---

### Engine 7 — VWAP Pressure *(new)*

**What it detects:** Institutional anchor levels. VWAP (Volume Weighted Average Price) resets at 9:15 AM daily and is the single most-watched intraday level by institutional desks.

| Setup | Condition | Direction |
|---|---|---|
| VWAP Bounce | Price near VWAP + bullish candle + volume ≥ 1.2× | BULLISH |
| VWAP Reclaim | Price crosses above VWAP with strong body | BULLISH |
| VWAP Rejection | Price near VWAP + bearish candle + volume ≥ 1.2× | BEARISH |
| VWAP Cross Down | Price crosses below VWAP with volume | BEARISH |

**VWAP band:** ±max(0.5×ATR, 0.3% of spot) — price must touch this band to count as a VWAP setup.

**VWAP computation:** Calculated fresh each tick from today's session candles: `Σ(typical_price × volume) / Σ(volume)`.

---

### Engine 7 (old) — IV Expansion *(Data-Only — not a triggering engine)*

**Status:** Runs every tick but does **not** count toward the 4-engine trigger threshold.

**Why demoted:** IV rises *because* a big candle already happened — it's a lagging confirmation, not a leading signal. Historical data showed 30% WR when IV Expansion was the deciding engine (fires in 86% of losing trades).

**Data still collected for ML:** `iv_skew_ratio`, `avg_atm_iv`, `iv_change_pct`, `iv_rank`

---

### Engine 8 — Market Regime

**What it detects:** Market structure classification to prevent wrong-type signals.

| Regime | Condition | Engine state |
|---|---|---|
| TRENDING | ADX > 25 AND Choppiness Index < 38.2 | Triggered → direction of dominant DI |
| RANGING | Choppiness Index > 61.8 | **Not triggered** (abstains — avoids mean-reversion counter-trend) |
| VOLATILE | ATR > 1.5× rolling ATR average | Triggered → recent momentum direction |

**Choppiness Index formula:** `100 × log₁₀(ΣTR / (HH − LL)) / log₁₀(14)` over 14 candles.
Responds in 1–2 candles vs ADX's 5–10 candle lag.

**Key design:** The engine abstains (`is_triggered = False`) in RANGING markets specifically so it doesn't add votes against breakout logic. This allows breakouts from ranges to still generate signals.

---

### MTF Alignment (confidence modifier)

Not an engine — a score modifier applied after all 8 engines vote.

| 5-min + 15-min bias vs signal direction | Score delta |
|---|---|
| Both agree with signal | +15 |
| One agrees, one neutral | +7 |
| Both neutral | 0 |
| One opposes, one neutral | −7 |
| Both oppose | −12 (and Trade Signal blocked) |

**ADX threshold:** A timeframe bias is only called directional if ADX ≥ 15 on that timeframe. Below that, it's NEUTRAL.

---

### Signal aggregation rules

```
Engines triggered  Action
──────────────────────────────────────────────────────────────────
< 4                No alert
≥ 4                Early Move Alert fired
                   (confidence = sum of engine scores / max_possible × 100%)

≥ 4 + ALL gates    Trade Signal (pending)
  Quality gates (ALL must pass):
  ├─ Compression breakout confirmed (close > compression range ± ATR)
  ├─ Volume ≥ 0.8× average (SIGNAL_MIN_VOLUME_RATIO)
  ├─ PCR ≥ 0.7 (SIGNAL_MIN_PCR)
  ├─ ADX ≥ 20 on 3m candle (TRADE_SIGNAL_MIN_ADX)
  ├─ |DI spread| ≥ 5 in signal direction (TRADE_SIGNAL_MIN_DI_SPREAD)
  ├─ MTF STRONG — both 5m+15m agree direction (TRADE_SIGNAL_REQUIRE_MTF_STRONG)
  ├─ Candle ≥ 33% formed (not a brand-new candle)
  └─ ML probability ≥ 0.45 if model is active (ML_SIGNAL_GATE_THRESHOLD)

Next candle open → Trade Signal fires as CONFIRMED
```

**Path A (normal escalation):** Existing early alert in same direction + all quality gates pass.

**Path B (quiet breakout):** No prior early alert, ≥ 10 minutes of silence, candle range > 1.5×ATR, DI triggered, engines ≥ 4.

**Confidence score:** `(total triggered engine scores) / (sum of active engine weights) × 100`. Only the 7 triggering engines contribute — Option Chain and IV Expansion weights are excluded from the denominator.

---

## 6. Alert System

### Alert types

| Type | Trigger | What it contains |
|---|---|---|
| `EARLY_MOVE` | ≥ 4 engines | Direction, confidence %, engines list, spot, PCR, ATR, ML score |
| `TRADE_SIGNAL` | ≥ 5 engines + breakout + candle-close confirm | All of above + suggested instrument, entry ref, SL, T1/T2/T3 |

### Instrument suggestion

When a Trade Signal fires, the aggregator suggests an options instrument:

- **Delta selection:** ATM (delta ≈ 0.50) when confidence < 65%; ITM (delta ≈ 0.60–0.65) when confidence ≥ 65%
- **Expiry:** Current weekly expiry; rolls to next expiry if DTE ≤ 1 day
- **Strike calculation:** ATM ± strike gap (NIFTY = 50, BANKNIFTY = 100, SENSEX = 100, MIDCPNIFTY = 25)

### Target levels (spot-based)

| Level | ATR multiplier |
|---|---|
| SL | entry ± 0.8 × ATR |
| T1 | entry ± 1.0 × ATR |
| T2 | entry ± 1.5 × ATR |
| T3 | entry ± 2.2 × ATR |

Direction determines sign: BULLISH adds for targets, subtracts for SL. BEARISH is reversed.

### Alert throttling

- **Early alerts:** 3-second minimum gap per direction per index (candle-interval throttle for DB writes; UI updated every tick)
- **Trade signals:** One per 3-min candle per index
- **MTF blocking:** If both 5-min and 15-min oppose the 3-min direction, Trade Signal is suppressed (Early Alert still fires)

### Delivery channels

| Channel | Early Move | Trade Signal | Confirmed |
|---|---|---|---|
| UI table update | ✓ | ✓ | ✓ |
| Sound beep | 1 × 800 Hz | 3 × 1000 Hz | 2 × 1000 Hz |
| Desktop popup | ✓ | ✓ | ✓ |
| Telegram | ✓ (if enabled) | ✓ (if enabled) | ✓ (if enabled) |

---

## 7. UI Tabs Reference

### Tab 1 — Dashboard

Real-time overview of all 4 indices.

**Per-index card shows:**
- Spot price + change + % change (vs previous close)
- ATR (14-period, 3-min)
- Volume ratio (current volume ÷ SMA-20)
- Futures OI classification with color coding:

| Classification | Condition | Color |
|---|---|---|
| ▲ LONG BUILDUP | Price ↑ + OI ↑ | Green |
| ▲ SHORT COVERING | Price ↑ + OI ↓ | Blue |
| ▼ SHORT BUILDUP | Price ↓ + OI ↑ | Red |
| ▼ LONG UNWINDING | Price ↓ + OI ↓ | Orange |
| ◆ NEUTRAL | No significant change | Gray |

- Engine trigger count and confidence %
- **INDEX FUTURES** panel with OI in Lakhs and 5/15/30-min OI change %

### Tab 2 — Scanner

Engine-by-engine live status for all indices.

**Per-engine row shows:**
- Engine name
- Triggered (✓ green) or Not triggered (× gray)
- Direction (BULLISH / BEARISH / NEUTRAL)
- Strength % (0–100)
- Score (0–25 contribution to confidence)
- Brief reason text

**Sensitivity slider:** Controls `MIN_ENGINES_FOR_SIGNAL` (3–6). Lower = more signals, higher = fewer but more selective. Setting persists across restarts in `user_settings.json`.

### Tab 3 — Options Flow

Future feature. Currently shows a placeholder.

### Tab 4 — Alerts

Main operational tab for monitoring and acting on signals.

**Left panel — Alert history table:**

| Column | Content |
|---|---|
| Time | HH:MM:SS |
| Index | NIFTY / BANKNIFTY / MIDCPNIFTY / SENSEX |
| Type | EARLY_MOVE / TRADE_SIGNAL |
| Direction | BULLISH / BEARISH |
| Confidence | 0–100% |
| Engines | Count of triggered engines |
| ML Score | Model probability (if available) |
| Outcome | WIN / LOSS / NEUTRAL (filled by tracker) |

Click any row to load full details in the right panel.

**Right panel — Trade card:**
- BUY/SELL action button
- Suggested instrument (e.g., `NSE:NIFTY27MAR23000CE`)
- Entry reference price, SL, T1, T2, T3
- Lot size, suggested delta

**Right panel — Details:**
- Engine breakdown (which triggered, which didn't)
- ML score with recommendation text
- Market context (spot, ATR, PCR, VIX)
- Outcome tracking (SL hit time, T1/T2/T3 hit times, MFE, MAE)

**ML Status header:** Phase (collecting / active), sample count, model version, F1 score, retrain button.

### Tab 5 — HQ Trades

Detailed trade-level analytics table. One row per Trade Signal.

| Column | Content |
|---|---|
| Alert ID | Unique alert reference |
| Signal Time | When the Trade Signal fired |
| Direction | BULLISH / BEARISH |
| Confidence | Engine confidence % |
| SL Hit | Time SL was hit (or — ) |
| T1/T2/T3 Hit | Time each target was hit (or —) |
| MFE | Maximum Favorable Excursion (in ATR units) |
| MAE | Maximum Adverse Excursion (in ATR units) |
| Exit Reason | SL / T3 / EOD |
| Outcome | WIN / LOSS / NEUTRAL |

### Tab 6 — Credentials

Broker authentication and settings.

- **Broker selector:** Dropdown (fyers, dhan, kite, upstox, mock)
- **Credential fields:** App ID, Secret Key, Access Token (masked)
- **Auth flow buttons:** Generate Auth URL, Exchange Code, Set Token Direct
- **Connection status:** Connected / Disconnected / Token expiry countdown
- **Save credentials** → persisted in `auth/credentials.json`

---

## 8. Database Schema

SQLite database at `nifty_trader.db`. Six tables.

---

### Table: `market_candles`

Stores all OHLCV candles (both spot and futures).

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `index_name` | TEXT | NIFTY / BANKNIFTY / MIDCPNIFTY / SENSEX |
| `timestamp` | DATETIME | Candle open time |
| `interval` | INTEGER | Candle minutes (3, 5, 15) |
| `open/high/low/close` | FLOAT | OHLC prices |
| `volume` | FLOAT | |
| `oi` | FLOAT | Open interest (futures only) |
| `is_futures` | BOOLEAN | True for futures candles |
| `candle_range` | FLOAT | high − low |
| `body_size` | FLOAT | |abs(close − open)| |
| `upper_wick/lower_wick` | FLOAT | Wick lengths |
| `is_bullish` | BOOLEAN | close ≥ open |
| `atr` | FLOAT | 14-period ATR at this candle |
| `plus_di/minus_di/adx` | FLOAT | Directional indicators |
| `volume_sma/volume_ratio` | FLOAT | Volume vs SMA-20 |
| `created_at` | DATETIME | Row insert time |

---

### Table: `option_chain_snapshots`

Snapshots of the option chain, refreshed every 15 seconds during market hours.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `index_name` | TEXT | |
| `timestamp` | DATETIME | Snapshot time |
| `expiry_date` | TEXT | e.g. "27-Mar-2025" |
| `spot_price` | FLOAT | |
| `atm_strike` | FLOAT | Nearest strike to spot |
| `total_call_oi/total_put_oi` | FLOAT | Sum across all strikes |
| `pcr` | FLOAT | Put-Call Ratio (OI-based) |
| `pcr_volume` | FLOAT | Put-Call Ratio (volume-based) |
| `max_pain` | FLOAT | Max pain price |
| `iv_rank` | FLOAT | IV rank (0–100) |
| `call_oi_change/put_oi_change` | FLOAT | % change vs prior snapshot |
| `pcr_change` | FLOAT | PCR delta vs prior |
| `oi_signal` | TEXT | BULLISH / BEARISH / NEUTRAL |
| `chain_data` | TEXT | Full JSON: [{strike, call_oi, put_oi, call_iv, put_iv, ...}] |
| `created_at` | DATETIME | |

---

### Table: `engine_signals`

Individual engine evaluation result for every candle evaluation.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `index_name` | TEXT | |
| `timestamp` | DATETIME | |
| `engine_name` | TEXT | compression / di_momentum / option_chain / etc. |
| `is_triggered` | BOOLEAN | |
| `direction` | TEXT | BULLISH / BEARISH / NEUTRAL |
| `strength` | FLOAT | 0.0 – 1.0 |
| `score` | FLOAT | 0 – 25 (contribution to confidence) |
| `features` | TEXT | JSON: {compression_ratio, atr, di_spread, ...} |
| `reason` | TEXT | Human-readable explanation |
| `created_at` | DATETIME | |

---

### Table: `alerts`

Every Early Move Alert and Trade Signal ever fired.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `index_name` | TEXT | |
| `timestamp` | DATETIME | When alert fired |
| `alert_type` | TEXT | EARLY_MOVE / TRADE_SIGNAL |
| `direction` | TEXT | BULLISH / BEARISH |
| `confidence_score` | FLOAT | 0 – 100 |
| `engines_triggered` | TEXT | JSON list: ["compression", "di_momentum", ...] |
| `engines_count` | INTEGER | |
| `spot_price` | FLOAT | Spot at alert time |
| `atm_strike` | FLOAT | |
| `pcr` | FLOAT | |
| `atr` | FLOAT | |
| `suggested_instrument` | TEXT | e.g. "NSE:NIFTY27MAR23000CE" |
| `entry_reference` | FLOAT | |
| `stop_loss_reference` | FLOAT | spot − 0.8×ATR |
| `target_reference` | FLOAT | spot + 1.0×ATR |
| `target1/target2/target3` | FLOAT | T1/T2/T3 levels |
| `ml_score` | FLOAT | 0–100 ML probability |
| `ml_phase` | INTEGER | 1 = collecting, 2 = model active |
| `outcome` | TEXT | WIN / LOSS / NEUTRAL (filled by tracker) |
| `outcome_pnl` | FLOAT | |
| `outcome_notes` | TEXT | |
| `outcome_timestamp` | DATETIME | |
| `is_valid` | BOOLEAN | Human label (for audit) |
| `raw_features` | TEXT | Full JSON feature dict |
| `created_at` | DATETIME | |

---

### Table: `trade_outcomes`

Tracks the full lifecycle of every Trade Signal.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `alert_id` | INTEGER FK → alerts | |
| `index_name` | TEXT | |
| `instrument` | TEXT | Options instrument symbol |
| `direction` | TEXT | BULLISH / BEARISH |
| `entry_time` | DATETIME | |
| `entry_spot` | FLOAT | Spot price at entry |
| `atr_at_signal` | FLOAT | ATR used for level computation |
| `spot_sl/spot_t1/spot_t2/spot_t3` | FLOAT | Computed levels |
| `sl_hit` | BOOLEAN | |
| `sl_hit_time/sl_hit_spot` | | |
| `t1_hit/t1_hit_time` | | |
| `t2_hit/t2_hit_time` | | |
| `t3_hit/t3_hit_time` | | |
| `mfe_atr` | FLOAT | Maximum Favorable Excursion ÷ ATR |
| `mae_atr` | FLOAT | Maximum Adverse Excursion ÷ ATR |
| `eod_spot` | FLOAT | 15:30 spot price |
| `exit_time` | DATETIME | |
| `exit_reason` | TEXT | SL / T3 / EOD |
| `outcome` | TEXT | WIN / LOSS / NEUTRAL |
| `pnl/pnl_percent` | FLOAT | |
| `status` | TEXT | OPEN / CLOSED |
| `post_close_t1/t2/t3_hit` | BOOLEAN | Did price later reach these levels after SL? |
| `post_close_max_fav/adv_atr` | FLOAT | Post-close excursion analysis |
| `post_sl_reversal` | BOOLEAN | Price reversed after SL hit |
| `post_sl_full_recovery` | BOOLEAN | Price fully recovered past T1 after SL |
| `post_close_eod_spot` | FLOAT | |
| `created_at` | DATETIME | |

---

### Table: `ml_feature_store`

79+ features extracted at every alert, with outcome feedback for ML training.

Key feature groups:

| Group | Features |
|---|---|
| **Engine outputs** | compression_ratio, atr_pct_change, plus_di, minus_di, adx, di_spread, pcr, volume_ratio, sweep_up/down, gamma_flip, iv_expanding, market_regime |
| **VWAP** | vwap, dist_to_vwap_pct, vwap_cross_up, vwap_cross_down, vwap_bounce, vwap_rejection, vwap_vol_ratio |
| **Engine trigger flags** | compression_triggered, di_triggered, option_chain_triggered, volume_triggered, liquidity_trap_triggered, gamma_triggered, iv_triggered, vwap_triggered, regime_triggered |
| **Timing** | mins_since_open, session, is_expiry, day_of_week, dte, candle_completion_pct |
| **Price context** | spot_vs_prev_pct, atr_pct_spot, chop, efficiency_ratio, gap_pct |
| **Candle patterns** | prev_body_ratio, prev_bullish, consec_bull, consec_bear, range_expansion |
| **Index correlation** | aligned_indices, market_breadth |
| **OI & Futures** | futures_oi_m, futures_oi_chg_pct, atm_oi_ratio |
| **MTF ADX + DI slopes** | adx_5m, plus_di_5m, minus_di_5m, adx_15m, plus_di_slope_5m, minus_di_slope_5m, plus_di_slope_15m, minus_di_slope_15m |
| **DI reversal flags** | di_reversal_5m, di_reversal_15m, di_reversal_both (1 = opposing DI fading = reversal setup) |
| **Price structure** | struct_5m, struct_15m, struct_5m_aligned, struct_15m_aligned, struct_both_aligned (HH/HL/LH/LL encoded) |
| **VIX** | vix, vix_high |
| **Signal identity** | direction_encoded, index_encoded, is_trade_signal |
| **Labels** | label (1=valid, 0=false, -1=unlabeled), sl_hit, t1_hit, t2_hit, t3_hit |

---

## 9. ML Pipeline

### Overview

The ML system is self-contained. It collects data passively, labels outcomes automatically, trains when enough data exists, and augments every alert with a probability score.

### Phase 1 — Data Collection (< 100 alerts)

- No model active
- All alerts use strategy rules only
- UI shows: `ML: Collecting data (N more samples needed)`
- Feature data is still saved for future training

### Phase 2 — First Model Training (≥ 100 labeled alerts)

- `ModelManager` detects ≥ 100 labeled records
- **Temporal split** (not random): oldest 80% = train, newest 20% = test — avoids lookahead bias
- RandomForest trained first (XGBoost if installed)
- Model saved to `models/model_vN.pkl`
- UI shows: `ML v1: MODERATE_BULLISH @ 65.3% [100 samples]`
- Every subsequent alert shows an ML probability score
- **ML gate active:** Trade Signals blocked if ML probability < 0.45

### Phase 3 — Continuous Improvement

- Every 50 new labeled samples → automatic retrain
- Version incremented (v2, v3, ...)
- Feature importance tracked per version

### Auto-labeling (every 15 minutes)

The `AutoLabeler` runs in background and assigns labels to unlabeled ML records:

```
For each unlabeled record:
  Look at the next 5 × 3-min candles after the alert

  If price moved ≥ 0.8 × ATR in the predicted direction:
    label = 1  (valid signal)

  Elif price moved ≥ 0.5 × ATR against the direction:
    label = 0  (false signal)

  Else:
    label = 0  (no meaningful move = false signal)
```

### ML score interpretation

| ML Score | Recommendation |
|---|---|
| ≥ 70% | STRONG (high confidence — take full size) |
| 55–70% | MODERATE (normal size) |
| 45–55% | WEAK (reduce size) |
| < 45% | LOW CONFIDENCE (avoid or skip) |

### Feature importance

After training, XGBoost reports which features matter most. Typically top features include:
- `engines_count` — how many engines agree
- `adx` — trend strength
- `mins_since_open` — time of day
- `candle_completion_pct` — how formed the candle was
- `compression_triggered` — volatility coiling present

---

## 10. Configuration Reference

All constants are in `nifty_trader/config.py`.

### Time settings

| Constant | Default | Description |
|---|---|---|
| `MARKET_OPEN_TIME` | 09:15 | NSE market open |
| `MARKET_CLOSE_TIME` | 15:30 | NSE market close |
| `SIGNAL_START_TIME` | 09:20 | Earliest signal window |
| `SIGNAL_END_TIME` | 15:00 | Latest signal window |
| `EXPIRY_DAY_SIGNAL_END_TIME` | 14:45 | Earlier cutoff on expiry day |

### Data fetching

| Constant | Default | Description |
|---|---|---|
| `CANDLE_INTERVAL_MINUTES` | 3 | Primary candle interval |
| `DATA_FETCH_INTERVAL_SECONDS` | 5 | Tick frequency |
| `CANDLE_HISTORY_COUNT` | 125 | Candles loaded at startup (~6.5 hours) |
| `OC_REFRESH_INTERVAL_SECONDS` | 15 | Option chain refresh |
| `OC_STALENESS_THRESHOLD_SEC` | 60 | Reject option chain older than this |

### Signal thresholds

| Constant | Default | Description |
|---|---|---|
| `MIN_ENGINES_FOR_ALERT` | 4 | Early Move Alert threshold (of 7 triggering engines) |
| `MIN_ENGINES_FOR_SIGNAL` | 4 | Trade Signal threshold |
| `SIGNAL_MIN_CANDLE_COMPLETION` | 0.33 | Candle must be ≥ 33% formed |
| `BREAKOUT_ATR_MULTIPLIER` | 1.0 | ATR multiple required for breakout confirm |
| `SIGNAL_MIN_VOLUME_RATIO` | 0.8 | Min volume vs 20-period average to allow Trade Signal |
| `SIGNAL_MIN_PCR` | 0.7 | Min PCR to allow Trade Signal |
| `TRADE_SIGNAL_MIN_ADX` | 20.0 | Min ADX on 3m candle — below this trend is too weak |
| `TRADE_SIGNAL_MIN_DI_SPREAD` | 5.0 | Min \|DI spread\| in signal direction |
| `TRADE_SIGNAL_REQUIRE_MTF_STRONG` | True | Both 5m+15m must agree (STRONG); PARTIAL/NEUTRAL blocked |
| `ML_SIGNAL_GATE_THRESHOLD` | 0.45 | Min ML probability to allow Trade Signal (Phase 2+) |

### Engine thresholds

| Engine | Key constant | Default |
|---|---|---|
| Compression | `COMPRESSION_RANGE_RATIO` | 0.70 |
| Compression | `ATR_DECLINING_LOOKBACK` | 3 candles |
| DI Momentum | `DI_SPREAD_WIDENING_THRESHOLD` | 2.0 points |
| DI Momentum | `DI_SPREAD_PCT_THRESHOLD` | 0.15 (15%) |
| Volume | `VOLUME_SPIKE_MULTIPLIER` | 1.5 |
| Volume | `VOLUME_AVERAGE_PERIOD` | 20 candles |
| Liquidity Trap | `LIQUIDITY_SWEEP_LOOKBACK` | 10 candles |
| Liquidity Trap | `LIQUIDITY_WICK_RATIO` | 0.50 |
| Gamma | `GAMMA_WALL_PROXIMITY_PCT` | 0.002 (0.2%) |
| VWAP | `VWAP_TOUCH_ATR_MULT` | 0.5 (0.5×ATR band) |
| VWAP | `VWAP_VOL_RATIO_MIN` | 1.2 (volume ≥ 1.2× avg) |
| VWAP | `VWAP_BODY_MIN_RATIO` | 0.35 (body ≥ 35% of range) |
| Market Regime | `REGIME_ADX_TRENDING` | 25.0 |
| Market Regime | `CHOP_RANGING_THRESHOLD` | 61.8 |
| Market Regime | `CHOP_TRENDING_THRESHOLD` | 38.2 |
| Option Chain *(data-only)* | `OI_CHANGE_SIGNIFICANCE` | 0.03 (3%) |
| IV Expansion *(data-only)* | `IV_EXPANSION_THRESHOLD` | 0.10 (10%) |

### MTF alignment

| Constant | Default | Description |
|---|---|---|
| `MTF_SCORE_BONUS` | +15 | Both TFs agree |
| `MTF_SCORE_PARTIAL_BONUS` | +7 | One TF agrees |
| `MTF_SCORE_WEAK_PENALTY` | −7 | One TF opposes |
| `MTF_SCORE_OPPOSING_PENALTY` | −12 | Both TFs oppose |
| `MTF_MIN_ADX` | 15.0 | Min ADX to call a TF direction |
| `MTF_BLOCK_ON_OPPOSING` | True | Block Trade Signal when both TFs oppose |

### Outcome tracking

| Constant | Default | Description |
|---|---|---|
| `OUTCOME_SL_ATR_MULT` | 0.8 | SL = entry ± 0.8 × ATR |
| `OUTCOME_T1_ATR_MULT` | 1.0 | T1 = entry ± 1.0 × ATR |
| `OUTCOME_T2_ATR_MULT` | 1.5 | T2 = entry ± 1.5 × ATR |
| `OUTCOME_T3_ATR_MULT` | 2.2 | T3 = entry ± 2.2 × ATR |
| `OUTCOME_EOD_TIME` | 15:30 | Force-close all open trades |

### ML settings

| Constant | Default | Description |
|---|---|---|
| `ML_MIN_SAMPLES_TO_ACTIVATE` | 100 | Samples before first training |
| `ML_RETRAIN_INTERVAL_SAMPLES` | 50 | New samples before retraining |
| `ML_LOOKAHEAD_CANDLES` | 5 | Candles to check for labeling |
| `ML_VALID_MOVE_ATR_MULT` | 0.8 | Min ATR move to label as valid |
| `AUTO_LABEL_INTERVAL_SECONDS` | 900 | 15 minutes |

### Index-specific settings

| Index | Lot size | Strike gap | Exchange |
|---|---|---|---|
| NIFTY | 75 | 50 | NSE |
| BANKNIFTY | 30 | 100 | NSE |
| MIDCPNIFTY | 120 | 25 | NSE |
| SENSEX | 20 | 100 | BSE |

---

## 11. Data Flow

### Startup sequence

```
1. Load config (credentials, indices, thresholds)
2. Connect to broker (load cached token or prompt for auth)
3. DataManager.start()
   a. Fetch 125 × 3-min candles per index (past 3 days)
   b. Fetch 80 × 5-min, 30 × 15-min candles per index
   c. Fetch current option chain per index
   d. Fetch near-month futures candles (OI = 0, filled by quotes tick)
   e. Restore intraday OI history from DB
   f. Compute initial indicators (ATR, DI, ADX, volume SMA)
4. OutcomeTracker._rehydrate()
   → Reload any OPEN trade outcomes from previous session
5. ModelManager.start()
   → Check for existing models, load latest active model
6. AutoLabeler.start()
   → Begin 15-min labeling loop
7. Start UI
```

### Tick loop (every 5 seconds, 09:15–15:30)

```
For each tick:
  1. Batch-fetch spot prices (all 4 indices, one API call)
  2. Batch-fetch futures quotes (OI + lp, one API call)
  3. For each index:
     a. Fetch latest forming 3-min candle
     b. If new candle started:
        - Close previous candle → save to DB
        - Fire any pending Trade Signal confirmations
     c. Merge futures volume into spot candle (if USE_FUTURES_VOLUME=True)
     d. Update IndexState (spot, candles, futures OI)
     e. Recompute indicators on updated DataFrame
     f. Every 15s: fetch option chain, save snapshot to DB
  4. Run SignalAggregator.evaluate() for each index
  5. OutcomeTracker.tick(spot_prices) — check SL/T1/T2/T3 levels
  6. Emit DataBridge.data_updated() → UI refresh
```

### Signal evaluation (per candle, per index)

```
1. Run all 8 engines on latest df, df_5m, df_15m, option_chain, futures_df
2. Collect triggered engines, directions, scores
3. Compute consensus direction (majority of triggered engines)
4. Compute confidence = sum of triggered engine scores (0–100)
5. Apply MTF alignment score delta
6. Check alert conditions:
   - existing_alert check (Path A) or quiet-breakout check (Path B)
   - cooldown: has a Trade Signal fired recently?
   - market hours: within 09:20–15:00?
7. If Early Move conditions met AND not recently saved:
   - save_alert(EARLY_MOVE) to DB
   - Return alert to UI every tick (for live confidence updates)
8. If Trade Signal conditions met:
   - save_alert(TRADE_SIGNAL) to DB
   - Buffer in _pending_confirm
9. On next candle open:
   - Fire buffered Trade Signal as CONFIRMED
   - AlertManager dispatches to all channels
10. Extract 60+ ML features, save to ml_feature_store
```

---

## 12. File Structure

```
nifty_trader/
├── main.py                          Entry point, logging setup, Qt app start
├── config.py                        All constants and thresholds
│
├── data/
│   ├── base_api.py                  Abstract broker adapter interface
│   ├── data_manager.py              IndexState + DataManager (tick loop)
│   ├── structures.py                Candle, OptionChain, OptionStrike, BrokerConnectionState
│   ├── expiry_calendar.py           Expiry date computation
│   └── adapters/
│       ├── fyers_adapter.py         Fyers OAuth2 + REST API
│       ├── mock_adapter.py          Synthetic data (GBM simulation)
│       ├── dhan_adapter.py          Dhan API stub
│       ├── kite_adapter.py          Kite Connect stub
│       └── upstox_adapter.py        Upstox API stub
│
├── engines/
│   ├── signal_aggregator.py         Central orchestration — runs all engines, emits alerts
│   ├── compression.py               Engine 1: volatility coiling
│   ├── di_momentum.py               Engine 2: directional pressure
│   ├── option_chain.py              Engine 3: smart money OI/PCR
│   ├── volume_pressure.py           Engine 4: institutional volume
│   ├── liquidity_trap.py            Engine 5: stop-hunt detection
│   ├── gamma_levels.py              Engine 6: MM hedging walls
│   ├── iv_expansion.py              Engine 7: IV surge
│   ├── market_regime.py             Engine 8: trending/ranging/volatile
│   └── mtf_alignment.py             MTF consensus scoring
│
├── database/
│   ├── models.py                    SQLAlchemy ORM models (6 tables)
│   └── manager.py                   DatabaseManager — CRUD + migrations
│
├── ml/
│   ├── feature_store.py             FEATURE_COLUMNS list + XGBoost/RF classifiers
│   ├── model_manager.py             Train/load/predict + version management
│   ├── outcome_tracker.py           SL/T1/T2/T3 level hit tracking
│   └── auto_labeler.py              Background outcome labeling (15-min loop)
│
├── alerts/
│   ├── alert_manager.py             Multi-channel dispatcher (UI + sound + popup + Telegram)
│   └── telegram_alert.py            Telegram bot message sender
│
└── ui/
    ├── main_window.py               MainWindow + DataBridge Qt signals
    ├── dashboard_tab.py             IndexCard + FuturesPanel (OI classification)
    ├── scanner_tab.py               EngineStatusWidget per index
    ├── alerts_tab.py                Alert table + trade card + outcome detail
    ├── hq_trades_tab.py             Detailed trade analytics
    ├── options_flow_tab.py          Options positioning (future feature)
    ├── credentials_tab.py           Broker auth + settings
    └── ml_report_widget.py          ML analytics (developer mode)
```

---

## 13. Outcome Tracking

### How it works

When a Trade Signal fires, `OutcomeTracker.register()` creates a `TradeOutcome` row and begins monitoring the trade every 5 seconds.

### Level hit logic (Phase 1 — OPEN)

```
Every 5 seconds:
  For each OPEN trade:
    spot = current spot price of index

    If direction == BULLISH:
      MFE = max(MFE, spot − entry_spot)        # best run
      MAE = max(MAE, entry_spot − spot)         # worst drawdown

      If spot ≤ SL level:   → SL_HIT → LOSS → move to Phase 2
      If spot ≥ T1 level:   → T1 milestone (stays OPEN)
      If spot ≥ T2 level:   → T2 milestone (stays OPEN)
      If spot ≥ T3 level:   → T3_HIT → WIN → move to Phase 2

    At 15:30 EOD: → force close all remaining as EOD
```

### Post-close monitoring (Phase 2)

After a trade closes (SL hit or T3 hit), monitoring continues until 15:30:

- Did price later reach T1, T2, T3 even after closing? (`post_close_t1/t2/t3_hit`)
- What was the maximum favorable excursion post-close?
- Did price fully reverse after SL hit? (`post_sl_reversal`, `post_sl_full_recovery`)

This data answers: "Was my SL too tight?" and "Did the original signal eventually work?"

### Outcome→ML feedback loop

When a trade closes, the outcome is written back to the corresponding `ml_feature_store` row:
- `sl_hit`, `t1_hit`, `t2_hit`, `t3_hit` flags updated
- `AutoLabeler` uses these in the next labeling pass
- Next model retrain includes this outcome-validated data

---

## 14. Troubleshooting

### No Trade Signals firing

**Check 1 — Engine count:** Open the Scanner tab. Are ≥ 5 engines triggering?

**Check 2 — Volume gate:** For cash indices, Fyers returns near-zero spot volume. The aggregator relaxes the gate to `vol_spike OR vol_triggered OR range_ok`. If volume is genuinely 0, signals can still fire.

**Check 3 — Market hours:** Trade Signals only fire 09:20–15:00 (14:45 on expiry day).

**Check 4 — MTF blocking:** If both 5-min and 15-min oppose the 3-min direction, Trade Signals are blocked (Early Alerts still fire).

**Check 5 — Compression breakout:** Trade Signal requires a compression breakout (close beyond ± 1×ATR of compression range). If no compression pattern exists, Path B (quiet breakout) fires if ≥ 10 min of silence + 1.5×ATR candle.

---

### OI showing "--" in dashboard

The INDEX FUTURES OI column shows "--" when `oi = 0.0` for the latest futures candle.

**Root cause:** `get_all_futures_quotes()` builds the near-month futures symbol (e.g., `NSE:NIFTY26MARFUT`) and fetches OI via Fyers quotes API. If there's a symbol format mismatch between what we construct and what Fyers returns, OI won't be set.

**Diagnostics:** Check the log file (`logs/niftytrader_YYYYMMDD.log`) during market hours for:
- `WARNING: Futures quotes API error:` → Fyers API call failing
- `WARNING: Futures quotes: unrecognised symbol 'X'` → symbol mismatch

**Note:** OI is only available during market hours. Outside hours, Fyers returns `oi=0`.

---

### Early Alerts but no Trade Signals — SENSEX sending too many

**SENSEX Trade Signal spam was a known bug** (12 signals in 26 minutes). Root cause: cooldown check ran AFTER DB write — signal was saved to DB then returned None to UI. Fixed by checking cooldown BEFORE save. If you see this in an older build, update to the latest version.

---

### Sensitivity slider resets on restart

The slider state is persisted in `user_settings.json`. If the file is deleted or corrupted, the slider resets to default (balanced = `MIN_ENGINES_FOR_SIGNAL = 5`).

---

### ML score always "Collecting data"

The XGBoost model activates after 100 labeled samples. Labels are assigned by `AutoLabeler` every 15 minutes by looking at price movement 5 candles after each alert. You need 100 Trade Signals that have been labeling-eligible (15+ minutes have passed since the alert) before the model activates.

---

### Token expired / auth required every day

Fyers tokens expire at midnight IST. This is a Fyers platform limitation — the token cannot be refreshed programmatically. You must repeat the OAuth flow each trading day. Consider using the **Set Token Direct** option if you have an automated way to fetch your token.

---

### Log file location

```
logs/niftytrader_YYYYMMDD.log
```

Log level is INFO by default. All WARNING and ERROR messages are always visible. DEBUG messages (detailed OI diagnostics, engine sub-conditions) require changing the log level in `main.py`:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```

---

*End of documentation — NiftyTrader Intelligence v3.0*
