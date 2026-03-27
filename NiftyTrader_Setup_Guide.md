# NiftyTrader — All Setups Explained

**Indices covered:** NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX
**Timeframe:** 3-minute candles (primary), 5m and 15m for confirmation
**Win rates** are from 6-day live data test (Mar 17–24 2026, ~4008 samples)

---

## How the System Works (Overview)

The system has **3 layers** before a trade fires:

```
Layer 1 → 8 Engines run every tick
Layer 2 → Early Move Alert (4+ engines agree)
Layer 3 → Trade Signal (passes all gates)
```

- **8 engines** scan price, volume, options, and market structure every few seconds
- When **4 or more engines** agree on a direction → **Early Move Alert** fires (⚡)
- When the Early Move Alert passes additional quality gates → **Trade Signal** fires (🎯)
- When a Trade Signal is confirmed at candle close → **Confirmed Signal** fires (✅)

---

## The 8 Engines

These are the building blocks. Each engine gives a YES/NO + direction + strength score.

### 1. Compression Engine
- Detects price coiling (low range, decreasing ATR, low volume)
- Like a spring being pressed — energy building before a move
- Triggers when: range ratio low + ATR declining + volume quiet

### 2. DI Momentum Engine
- Uses ADX + Plus DI + Minus DI indicators
- Detects directional pressure forming *before* ADX confirms the trend
- BULLISH: Plus DI rising and crossing above Minus DI
- BEARISH: Minus DI rising and crossing above Plus DI

### 3. Volume Pressure Engine
- Detects institutional buying or selling activity
- Compares current candle volume to recent average
- Triggers when volume is significantly above normal (volume_ratio > threshold)

### 4. Liquidity Trap Engine
- Detects stop-hunt sweeps followed by reversal
- Example: price dips below a recent low (triggering retail stop losses) then reverses sharply
- Signals that smart money has entered after clearing stops

### 5. Gamma Levels Engine
- Uses option chain data to find levels where Market Makers must hedge
- Identifies gamma walls (strikes with very high OI) that act as support/resistance
- Gamma flip level = price above which MM goes long delta, below which they short

### 6. Market Regime Engine
- Classifies the market into: **TRENDING / RANGING / VOLATILE**
- Uses: Choppiness Index + ADX + ATR slope combined
- Most setups require TRENDING regime (ADX high + low chop + ATR expanding)
- RANGING = avoid (whipsaw risk), VOLATILE = avoid (premium too high)

### 7. Option Chain Engine (data-only)
- Reads PCR (Put-Call Ratio), Max Pain, OI changes
- PCR > 1.2 = more puts = bearish sentiment
- PCR < 0.8 = more calls = bullish sentiment
- Captures OI buildup at ATM strike for momentum confirmation

### 8. IV Expansion Engine (data-only)
- Monitors IV Rank and ATM IV levels
- High IV = options expensive, avoid buying
- Low IV = options cheap, good time to buy

> **Note:** Engines 7 and 8 are data-only — they do NOT count toward the 4-engine trigger threshold. They are used as ML features and confirmation only.

---

## Two Additional Engines (Confirmation)

### VWAP Pressure Engine
- Detects price crossing and holding above/below VWAP
- BULLISH: price bouncing off VWAP from above
- BEARISH: price rejected at VWAP from below
- Used as a setup filter (S20)

### MTF Alignment Engine (Multi-Timeframe)
- Checks if 5m and 15m charts agree with the 3m signal direction
- **STRONG** = both 5m and 15m agree → highest quality
- **PARTIAL** = only one agrees → moderate quality
- **NEUTRAL/WEAK/OPPOSING** = no alignment → Trade Signal is blocked

---

## Trade Signal Gates (What Must Pass to Fire a Trade)

Even when 4+ engines agree, the system applies these additional filters:

| Gate | Condition |
|------|-----------|
| Regime | Must be TRENDING (not RANGING or VOLATILE) |
| MTF | Must be STRONG (both 5m + 15m agree) |
| ADX | Must be above minimum threshold |
| DI Spread | Plus DI must lead for BULL, Minus DI must lead for BEAR |
| Volume Ratio | Above minimum threshold |
| PCR | Within acceptable range |
| ML Score | Model confidence above threshold |
| Candle Completion | Signal not fired in first 33% of candle |
| VIX | India VIX must be below max threshold |
| Event Window | No major economic events active |
| Cooldown | One trade signal per candle per index |

---

## The 23 Named Setups

These are pattern labels applied to every Early Move Alert / Trade Signal.
Multiple setups can fire at the same time for one signal.
They are used for performance tracking and ML training.

### Grading Scale
- **A++** → Best setups (83%+ win rate)
- **A+** → High quality (67–76% win rate)
- **A** → Strong (56–62% win rate)
- **A-** → Decent edge (53–56% win rate)
- **B** → Moderate (30–40% win rate)
- **C-** → Weak (19% win rate)
- **D / F** → Below baseline (data collection only)

---

### TIER F / D — Below Baseline (Data Collection Only)

---

#### S01 — DI Aligned (Grade: D, WR: 12%)
- **What fires it:** DI is aligned with signal direction on 3m chart
- **Condition:** Plus DI > Minus DI for BULL / Minus DI > Plus DI for BEAR
- **Why it's weak:** DI alignment alone gives no edge — too many false signals
- **Use:** Baseline reference only

---

#### S02 — DI Ratio Strong (Grade: C-, WR: 19%)
- **What fires it:** DI ratio shows strong bias
- **Condition:** Plus DI / Minus DI > 1.2 for BULL OR < 0.8 for BEAR
- **Why it's weak:** Ratio bias alone still not reliable enough without regime filter
- **Use:** Data collection

---

#### S03 — DI + 3 Engines (Grade: C-, WR: 19%)
- **What fires it:** DI aligned AND 3 or more engines triggered
- **Condition:** DI aligned + engines_count ≥ 3
- **Why it's weak:** 3 engines is the early move threshold — still too many RANGING signals
- **Use:** Data collection

---

### TIER B — Moderate Edge

---

#### S04 — DI + 4 Engines (Grade: B, WR: 40%)
- **What fires it:** DI aligned AND 4 or more engines triggered
- **Condition:** DI aligned + engines_count ≥ 4
- **Meaning:** When 4 engines agree AND DI is directional, win rate jumps to 40%
- **Still missing:** Regime filter — fires in both TRENDING and RANGING markets

---

#### S20 — DI + Trending + VWAP (Grade: B, WR: 30%)
- **What fires it:** DI aligned + TRENDING regime + VWAP engine triggered
- **Condition:** DI aligned + regime = TRENDING + VWAP triggered
- **Note:** Needs more data to validate — only 30% so far
- **Use:** Data collection — may improve as VWAP engine matures

---

### TIER A- — Single High-Quality Filter (53–56%)

---

#### S05 — Trending Regime Only (Grade: A-, WR: 55.8%)
- **What fires it:** Market is in TRENDING regime
- **Condition:** Market Regime Engine classifies market as TRENDING
- **Meaning:** Just being in a trending market gives 55.8% win rate
- **Why:** Trending markets have momentum — directional bets work better

---

#### S06 — Option Chain Triggered (Grade: A-, WR: 53.3%)
- **What fires it:** Option chain engine triggers
- **Condition:** PCR + OI data confirms directional bias
- **Meaning:** When options market aligns with signal direction, 53.3% win rate
- **Why:** Options market reflects institutional positioning

---

#### S07 — Option Chain + DI Aligned (Grade: A-, WR: 56.3%)
- **What fires it:** Option chain triggered AND DI is aligned
- **Condition:** OC triggered + DI aligned
- **Meaning:** Two independent signals agree — options positioning + price momentum
- **Better than S06 alone** because DI filters out weak option signals

---

#### S08 — Option Chain + Trending (Grade: A-, WR: 53.6%)
- **What fires it:** Option chain triggered AND market is TRENDING
- **Condition:** OC triggered + regime = TRENDING
- **Meaning:** Options positioning in a trending market environment
- **Note:** Similar to S06 but regime-filtered — slightly better quality

---

#### S17 — 4+ Engines + Trending (Grade: A-, WR: 55.8%)
- **What fires it:** 4 or more engines triggered AND market is TRENDING
- **Condition:** engines_count ≥ 4 + regime = TRENDING
- **Meaning:** Volume consensus in a trending market
- **Better than S04** because the regime filter removes RANGING false signals

---

#### S18 — 4+ Engines + Option Chain (Grade: A-, WR: 53.3%)
- **What fires it:** 4 or more engines triggered AND option chain confirms
- **Condition:** engines_count ≥ 4 + OC triggered
- **Meaning:** Engine agreement + options market backing the same direction

---

### TIER A — Strong Combinations (56–62%)

---

#### S09 — DI + Trending (Grade: A, WR: 56.6%)
- **What fires it:** DI aligned + market is TRENDING
- **Condition:** DI aligned + regime = TRENDING
- **Meaning:** Core best-balanced setup — price direction + trend environment
- **All 4 indices:** Works across NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX
- **Considered the baseline quality setup**

---

#### S10 — Option Chain + DI + Trending (Grade: A, WR: 56.1%)
- **What fires it:** All three: OC triggered + DI aligned + TRENDING
- **Condition:** Triple confirmation from 3 independent sources
- **Meaning:** Options, price momentum, and market structure all agree

---

#### S12 — NIFTY Only: DI + Trending (Grade: A, WR: 62.1%)
- **What fires it:** Same as S09 but NIFTY only
- **Condition:** DI aligned + regime = TRENDING — restricted to NIFTY
- **Why higher WR:** NIFTY is the most liquid index — cleaner signals, less noise
- **NIFTY-specific tracking**

---

#### S15 — MIDCPNIFTY Only: DI + Trending (Grade: A, WR: 56.6%)
- **What fires it:** DI aligned + TRENDING — MIDCPNIFTY only
- **Condition:** Same as S09 but for MIDCPNIFTY
- **Why track separately:** MIDCPNIFTY has different volatility characteristics
- **Win rate same as all-index S09** — consistent across indices

---

#### S16 — SENSEX Bear + Trending (Grade: A, WR: 58.5%)
- **What fires it:** SENSEX BEARISH signals in TRENDING regime
- **Condition:** DI aligned + TRENDING — SENSEX only, BEARISH only
- **Why only bear:** SENSEX bullish signals showed poor win rate; bear signals are cleaner
- **Key insight:** SENSEX bears better than it bulls in this setup

---

#### S19 — PCR Bear Confirmation (Grade: A, WR: 60.1%)
- **What fires it:** PCR > 1.2 + DI aligned + TRENDING — BEARISH only
- **Condition:** Put-Call Ratio above 1.2 means more puts → bearish institutional positioning
- **Meaning:** When options market is already positioned bearish AND trend confirms → 60% WR
- **Only fires for BEARISH signals** — PCR > 1.2 is a bear-side filter

---

#### S21 — MIDCPNIFTY: OC + DI + Trending (Grade: A, WR: 53.7%)
- **What fires it:** Option chain + DI aligned + TRENDING — MIDCPNIFTY only
- **Condition:** Triple confirmation for MIDCPNIFTY specifically
- **Meaning:** MIDCPNIFTY with full three-source confirmation

---

#### S23 — DI + Trending + MTF Strong (Grade: A, WR: 58%)
- **What fires it:** DI aligned + TRENDING + MTF alignment is STRONG
- **Condition:** Both 5m AND 15m timeframes agree with the 3m signal direction
- **Meaning:** The trade setup is visible on all three timeframes simultaneously
- **Best sign:** When 3m, 5m, 15m all agree — strong momentum confirmation
- **All indices, both directions**

---

### TIER A+ — High Win Rate Setups (67–76%)

---

#### S11 — DI + Trending + High Volume (Grade: A+, WR: 67.2%)
- **What fires it:** DI aligned + TRENDING + volume_ratio ≥ 1.5
- **Condition:** Institutional volume surge in a trending market with DI confirmation
- **Meaning:** Large players are entering aggressively — 67% win rate
- **Volume_ratio ≥ 1.5** = current volume is 1.5x or more above recent average
- **All 4 indices, both directions**
- **This setup is also the basis of the S11 Paper Trade Monitor** (see below)

---

#### S14 — BANKNIFTY Bear + Trending (Grade: A+, WR: 71.1%)
- **What fires it:** BANKNIFTY BEARISH signals in TRENDING regime
- **Condition:** DI aligned + TRENDING — BANKNIFTY only, BEARISH only
- **Why only bear:** BANKNIFTY bullish signals showed poor win rate in testing
- **Key insight:** BANKNIFTY bear setups have strong institutional edge
- **Bull signals on BANKNIFTY are blocked in this setup**

---

#### S22 — BANKNIFTY: OC + DI + Trending Bear (Grade: A+, WR: 76.7%)
- **What fires it:** OC triggered + DI aligned + TRENDING — BANKNIFTY bear only
- **Condition:** Triple confirmation on BANKNIFTY in bear direction
- **Best non-S13 setup** — 76.7% win rate
- **The option chain being triggered on a BANKNIFTY bear in a trending market is very strong**

---

### TIER A++ — Best Setup Found

---

#### S13 — NIFTY: DI + Trending + High Volume (Grade: A++, WR: 83.3%)
- **What fires it:** DI aligned + TRENDING + volume_ratio ≥ 1.5 — NIFTY only
- **Condition:** Same as S11 but restricted to NIFTY
- **Why it's the best:** NIFTY + high volume surge + trend = highest conviction setup
- **83.3% win rate** from live testing (best found across all 23 setups)
- **How to use:** When S13 fires, it is the highest-confidence signal in the system

---

## S11 Paper Trade Monitor (Special System)

The S11 Monitor is a **standalone paper trading system** built around the S11/S13 setup condition.

### What it is
- Automatically opens simulated 2-lot paper trades when S11 condition is met
- Tracks the trade live against real market prices
- Closes automatically on SL, T3, or end of day
- All results saved to database for performance tracking

### S11 Condition (must pass all three)
1. Market regime = **TRENDING**
2. Volume ratio ≥ **1.5** (institutional volume surge)
3. DI aligned: Plus DI > Minus DI (BULL) OR Minus DI > Plus DI (BEAR)

### Trade Structure (2 lots per trade)
| Level | Description |
|-------|-------------|
| Entry | ATM option premium at signal time |
| Stop Loss | Entry spot ± (ATR × SL multiplier) |
| Target 1 (T1) | Entry spot ± (ATR × T1 multiplier) — 50% partial |
| Target 2 (T2) | Entry spot ± (ATR × T2 multiplier) — trail SL to breakeven |
| Target 3 (T3) | Entry spot ± (ATR × T3 multiplier) — full close |

### Trade Management Rules
- **T2 hit** → Stop Loss trails to entry price (breakeven — can't lose after T2)
- **T3 hit** → Full position closed, WIN
- **SL hit before T2** → Full loss
- **SL hit after T2** → 50% booked at T2 price, 50% at SL price → still WIN
- **End of Day (15:30)** → Position force-closed
  - T1 was hit before EOD → WIN (50% booked at T1, 50% at EOD LTP)
  - T1 not hit before EOD → NEUTRAL (closed at EOD LTP)

### P&L Calculation (uses real live option LTPs)
| Close Reason | Formula |
|---|---|
| T3 hit | (Exit LTP − Entry) × Units |
| SL after T2 | (T2 LTP − Entry) × Units × 0.5 + (SL LTP − Entry) × Units × 0.5 |
| SL before T2 | (Exit LTP − Entry) × Units — LOSS |
| EOD after T1 | (T1 LTP − Entry) × Units × 0.5 + (EOD LTP − Entry) × Units × 0.5 |
| EOD no T1 | (EOD LTP − Entry) × Units — NEUTRAL |

### Sound Alert
- **Only S11 signals make a sound** — all other early moves are silent
- Trade Signal = 3 beeps
- Confirmed Signal = 2 beeps
- Early Move = 1 beep

### Where to See It in the App
- Tab: **⚡ S11** (last tab)
- Shows: Early alerts today / Open positions / Closed today / Stats (Win%, T2%, T3%, Total P&L)

---

## Quick Reference — Best Setups to Watch

| Setup | Index | Direction | Win Rate | Key Condition |
|-------|-------|-----------|----------|---------------|
| S13 | NIFTY only | Both | 83.3% | DI + Trending + Volume ≥ 1.5x |
| S22 | BANKNIFTY only | Bear only | 76.7% | OC + DI + Trending |
| S14 | BANKNIFTY only | Bear only | 71.1% | DI + Trending |
| S11 | All indices | Both | 67.2% | DI + Trending + Volume ≥ 1.5x |
| S19 | All indices | Bear only | 60.1% | PCR > 1.2 + DI + Trending |
| S12 | NIFTY only | Both | 62.1% | DI + Trending |
| S23 | All indices | Both | 58.0% | DI + Trending + MTF Strong |
| S16 | SENSEX only | Bear only | 58.5% | DI + Trending |
| S09 | All indices | Both | 56.6% | DI + Trending (baseline) |

---

## Key Terms Glossary

| Term | Meaning |
|------|---------|
| DI Aligned | Plus DI > Minus DI for BULL, Minus DI > Plus DI for BEAR |
| TRENDING | Market regime: ADX high, low chop, ATR expanding |
| Volume Ratio | Current volume ÷ recent average volume |
| PCR | Put-Call Ratio (PCR > 1 = more puts = bearish sentiment) |
| MTF Strong | Both 5m and 15m timeframes confirm the 3m signal direction |
| ATR | Average True Range — measures volatility, used for SL and target levels |
| OC Triggered | Option Chain engine detected unusual OI build or PCR shift |
| MFE / MAE | Max Favorable Excursion / Max Adverse Excursion (in ATR units) |
| Units | Lots × Lot Size (e.g. 2 lots × 75 NIFTY = 150 units) |
| Breakeven Trail | After T2 hit, SL moves to entry price — trade cannot lose money |
