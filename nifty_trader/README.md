# NiftyTrader Intelligence System

A local, desktop-based intraday trading intelligence application for Indian index options.
Built with Python + PySide6. Runs entirely on your machine — no browser, no cloud.

---

## Engines

### Triggering Engines (7) — vote toward alert threshold

| # | Engine | What it detects |
|---|--------|----------------|
| 1 | Compression | Price coiling before expansion (range/ATR contraction) |
| 2 | DI Momentum | Directional pressure before ADX confirms (+DI/-DI slope) |
| 3 | Volume Pressure | Institutional accumulation/distribution (volume spike pattern) |
| 4 | Liquidity Trap | Stop-hunt sweep + reversal (wick rejection) |
| 5 | Gamma Levels | MM delta-hedge walls and gamma flip (OI-based) |
| 6 | VWAP Pressure | Price bouncing/crossing VWAP with volume (institutional anchor) |
| 7 | Market Regime | Trending/Ranging/Volatile classification — fires only in TRENDING regime |

### Data-Only Engines — run every tick, feed ML features, do not vote

| Engine | Why data-only | Data saved |
|--------|--------------|-----------|
| Option Chain | OI lags price — 27% WR as deciding engine | PCR, max pain, OI change, iv_rank |
| IV Expansion | IV rises AFTER big candle — lagging confirmation, 30% WR | iv_rank, avg_atm_iv, iv_change_pct |

---

## Signal Pipeline

```
Live Market Data (every 5s — Fyers batch quotes API)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│                   7 TRIGGERING ENGINES                        │
│  Compression · DI · Volume · Liquidity · Gamma · VWAP · Regime│
│  (+ 2 data-only: Option Chain · IV Expansion)                │
│  (+ 1 modifier:  MTF Alignment — adjusts score, no gate)     │
└──────────────────────────────────────────────────────────────┘
        │
        ▼  ≥ 3 engines align → save ML features
┌──────────────────────┐
│   EARLY MOVE ALERT   │  → Sound + Popup + Telegram (3 retries)
│   Direction + Score  │  → Logged to DB + ML store
└──────────────────────┘
        │
        ▼  + all quality gates pass
┌──────────────────────────────────────────────────┐
│    TRADE SIGNAL (pending candle close)            │
│  Quality gates (all must pass):                   │
│  ├─ ≥ 4 engines triggered                        │
│  ├─ Compression breakout confirmed                │
│  ├─ Volume ≥ 1.5× 20-bar average                 │
│  ├─ PCR ≥ 0.7                                    │
│  ├─ ADX ≥ 20 on 3m candle                        │
│  ├─ |DI spread| ≥ 5 in signal direction           │
│  ├─ MTF STRONG (both 5m+15m agree)               │
│  ├─ Regime = TRENDING                             │
│  ├─ VIX ≤ 20 (if gate enabled)                   │
│  ├─ No active event block (RBI/Fed/Budget)        │
│  └─ ML probability ≥ 0.50 (if model trained)     │
└──────────────────────────────────────────────────┘
        │
        ▼  next candle open
┌──────────────────────┐
│  CONFIRMED SIGNAL    │  → Instrument suggestion (CE/PE, strike, expiry)
│  Entry / SL / T1/T2/T3│  → Outcome tracking begins
└──────────────────────┘
        │
        ▼  SL / T1 / T2 / T3 hit or 15:30 IST EOD
┌──────────────────────┐
│  OUTCOME LABELED     │  → P&L in ₹ recorded to DB
│  ML training sample  │  → Auto-retrain every 50 new samples
└──────────────────────┘
```

---

## File Structure

```
nifty_trader/
│
├── main.py                      ← Application entry point
├── config.py                    ← All thresholds, credentials, settings
├── requirements.txt
│
├── data/
│   ├── adapters/
│   │   ├── fyers_adapter.py     ← Fyers API (primary broker); lp/cp fix, token cache, rate-limit guards
│   │   ├── dhan_adapter.py      ← Dhan adapter
│   │   ├── kite_adapter.py      ← Zerodha Kite adapter
│   │   ├── upstox_adapter.py    ← Upstox adapter
│   │   └── mock_adapter.py      ← Synthetic OHLCV for testing (no broker needed)
│   ├── data_manager.py          ← Live data ingestion; tick loop; _market_active guard; circuit breaker
│   ├── expiry_calendar.py       ← Broker-driven expiry dates (thread-safe cache)
│   ├── event_calendar.py        ← Economic event calendar (RBI MPC, FOMC, Budget)
│   ├── event_updater.py         ← Background event data fetcher (updates from official sites)
│   ├── eod_auditor.py           ← EOD data audit: fills missing candles, validates OC snapshots at 15:31 IST
│   ├── bs_utils.py              ← Black-Scholes IV computation + Greeks (used for option price estimation)
│   ├── structures.py            ← Candle / OptionChain data structures
│   └── base_api.py              ← Abstract broker adapter interface (all adapters implement this)
│
├── engines/
│   ├── compression.py           ← Engine 1: Price compression (range/ATR contraction)
│   ├── di_momentum.py           ← Engine 2: DI directional pressure (+DI/-DI slope)
│   ├── volume_pressure.py       ← Engine 3: Institutional volume (futures volume spike)
│   ├── liquidity_trap.py        ← Engine 4: Stop-hunt detection (wick rejection)
│   ├── gamma_levels.py          ← Engine 5: MM gamma walls and flip levels
│   ├── vwap_pressure.py         ← Engine 6: VWAP bounce/cross with volume confirmation
│   ├── market_regime.py         ← Engine 7: Trending/Ranging/Volatile classification
│   ├── option_chain.py          ← Data-only: PCR, OI change, Max Pain (ML features only)
│   ├── iv_expansion.py          ← Data-only: IV skew, iv_rank, iv_change_pct (ML features only)
│   ├── mtf_alignment.py         ← MTF confidence modifier (5m + 15m alignment — not a gate)
│   ├── s11_monitor.py           ← S11 setup monitor: prior session high/low breakouts (named setups)
│   ├── setup_screener.py        ← Evaluates all 23 named setups per signal tick
│   └── signal_aggregator.py     ← Orchestrator: runs all engines → EarlyMoveAlert → TradeSignal
│
├── alerts/
│   ├── alert_manager.py         ← Dispatches: popup, sound, Telegram (once-per-alert)
│   └── telegram_alert.py        ← Telegram Bot API
│
├── trading/
│   └── order_manager.py         ← Auto-trading: OFF / PAPER / LIVE modes
│
├── database/
│   ├── models.py                ← SQLAlchemy ORM (tables: alerts, signals, outcomes,
│   │                               trade_outcomes, ml_features, setup_alerts)
│   └── manager.py               ← CRUD + auto-migration on startup
│
├── ui/
│   ├── main_window.py           ← Main window, tab container, thread bridge, update callbacks
│   ├── dashboard_tab.py         ← Tab 1: Live index cards, engine status, active alerts
│   ├── scanner_tab.py           ← Tab 2: Engine status per index (detailed view)
│   ├── alerts_tab.py            ← Tab 3: Alert log with full trade card + ML score
│   ├── hq_trades_tab.py         ← Tab 4: Trade outcomes + realized P&L analytics
│   ├── setup_tab.py             ← Tab 5: Named setup performance (win rate, avg P&L)
│   ├── options_flow_tab.py      ← Tab 6: Options flow / OI analysis / PCR chart
│   ├── ledger_tab.py            ← Tab 7: Trade ledger / P&L history
│   ├── s11_tab.py               ← Tab 8: S11 monitor — prior session high/low breakout tracking
│   ├── ml_report_widget.py      ← ML model report: feature importance, win rate by regime
│   └── credentials_tab.py       ← Broker auth (Fyers OAuth, hot-swap broker at runtime)
│
└── ml/
    ├── feature_store.py         ← 93 FEATURE_COLUMNS definitions + load_dataset()
    ├── model_manager.py         ← Train/load/predict + auto-retrain (thread-safe singleton); feature column validation
    ├── setups.py                ← 23 named setup definitions (condition lambda + grade + metadata)
    ├── historical_trainer.py    ← Fetch historical Fyers data → build ML training set from candles
    ├── auto_labeler.py          ← Background outcome labeling every 15 min; NSE holiday-aware; P1/P2/P3/P4 priority
    ├── outcome_tracker.py       ← SL/T1/T2/T3 level hit detection, MFE/MAE, realized P&L ₹
    └── readiness_checker.py     ← Checks if ML system has enough labeled data to train; reports readiness status
```

---

## ML Feature Groups (93 features)

| Group | Key features | Count |
|-------|-------------|-------|
| Price momentum | compression_ratio, atr, atr_pct_change, range_expansion | 4 |
| DI / Directional | adx, plus_di, minus_di, di_spread, di_slope (3m/5m/15m) | 12 |
| Volume | volume_ratio (20-bar), volume_ratio_5bar, stealth_accumulation | 4 |
| VWAP | dist_to_vwap_pct, vwap_bounce, vwap_cross_up/down, vwap_rejection, vwap_vol_ratio | 7 |
| Options chain | pcr, oi_change_pct, avg_call_iv (iv_rank), max_pain_dist_pct | 6 |
| IV Expansion | avg_atm_iv, iv_skew_ratio, iv_change_pct, iv_expanding | 4 |
| Market structure | struct_5m, struct_15m, struct_5m_aligned, struct_15m_aligned, struct_both_aligned | 5 |
| Market regime | chop, regime_adx, atr_ratio, regime_label_encoded, efficiency_ratio | 5 |
| Time context | session, mins_since_open, is_expiry, day_of_week, dte | 6 |
| MTF DI slopes | plus/minus_di_slope_5m/15m, di_reversal_5m/15m/both | 10 |
| Multi-index breadth | indices_bull_count, indices_bear_count, breadth_aligned | 3 |
| Futures / OI | futures_oi_m, futures_oi_chg_pct, basis_slope, excess_basis, oi_regime | 9 |
| VIX | vix, vix_high | 2 |
| Pre-open | preopen_gap_pct (frozen at 9:15 IST) | 1 |
| Signal identity | direction_encoded, index_encoded, engines_count, is_trade_signal | 4 |
| Candle patterns | prev_body_ratio, consec_bull, consec_bear, range_expansion, prev_bullish | 4 |
| Engine trigger flags | compression/di/volume/liq/gamma/vwap/iv/oc_triggered (8 flags) | 8 |

**Feature collision protection (v3.1):** `_get_ml_prediction` uses explicit per-engine mapping
identical to `_save_ml_features`. Three silent collisions resolved: `iv_rank` (option_chain only),
`volume_ratio` (volume_pressure only), `adx` (di_momentum only — regime uses `regime_adx`).

**Feature validation (v3.2):** At model load, saved `feature_cols` are compared against current
`FEATURE_COLUMNS`. Mismatch logged as WARNING — indicates model was trained with a different
engine set and should be retrained.

---

## P&L Tracking

Outcomes are tracked in rupees using `lot_size × premium_move`:

| Index | Lot size (SEBI Mar 2026) | P&L per point |
|-------|--------------------------|---------------|
| NIFTY | 65 | ₹65 per point |
| BANKNIFTY | 30 | ₹30 per point |
| MIDCPNIFTY | 120 | ₹120 per point |
| SENSEX | 20 | ₹20 per point |

Lot sizes are sourced from `config.SYMBOL_MAP` and auto-updated from the broker on every option chain refresh. If the broker returns a different lot size than the hardcoded value, it is written back to `config.SYMBOL_MAP` and logged.

P&L values (`realized_pnl`) are stored per trade in `trade_outcomes` and surfaced in:
- **HQ Trades tab** — per-signal P&L column
- **Setup Performance tab** — avg P&L and total P&L per named setup

---

## Named Setups (23)

The `SetupScreener` + `ml/setups.py` evaluate 23 named intraday setups every signal cycle.
Each setup has a name, grade (A/B/C), and condition function over live engine feature dicts.

Examples: `Breakout Compression`, `VWAP Bounce Bull`, `Gamma Wall Reversal`,
`Trend Continuation DI`, `Liquidity Sweep Bull/Bear`, `Pre-Open Gap Fill`, etc.

Matched setup names are stored in `setup_alerts` DB table and shown in the
**Setup Performance tab** with live win rate, T2/T3 hit counts, and ₹ P&L.

---

## Expiry Calendar

All live expiry dates are fetched from the broker (`get_expiry_dates()`) on every option
chain refresh and cached in a thread-safe module-level dict (`expiry_calendar.py`).

Current SEBI schedule (Sep 2025+):

| Index | Options expiry | Futures expiry |
|-------|---------------|----------------|
| NIFTY | Every **Tuesday** (weekly) | Last Tuesday of month |
| BANKNIFTY | Last **Tuesday** of month (monthly) | Last Tuesday of month |
| MIDCPNIFTY | Last **Tuesday** of month (monthly) | Last Tuesday of month |
| SENSEX | Every **Thursday** (weekly) | Last Thursday of month |

> Historical schedules handled automatically:
> - Before Nov 20 2024: all weekly (NIFTY/BANKNIFTY=Thu, MIDCPNIFTY=Mon, SENSEX=Fri)
> - Nov 2024 – Aug 2025: mixed weekly/monthly with Thursday/Friday expiries
> - Sep 2025+: current schedule above

Hardcoded weekday math is only used as a cold-start fallback before the first broker
connection. After connection, all expiry logic is broker-driven via `get_expiry_dates()`.

---

## Auto Trading

Controlled by `config.AUTO_TRADE_ENABLED` (runtime toggle) and `config.AUTO_TRADE_PAPER_MODE`:

| Setting | Behavior |
|---------|---------|
| `AUTO_TRADE_ENABLED = False` | No orders placed — dashboard only (default) |
| `AUTO_TRADE_ENABLED = True, AUTO_TRADE_PAPER_MODE = True` | PAPER: simulated fills, P&L tracked without real orders |
| `AUTO_TRADE_ENABLED = True, AUTO_TRADE_PAPER_MODE = False` | LIVE: real Fyers bracket orders placed at exchange |

### Quality Gates (all must pass before any auto-order)
- Signal confidence ≥ `AUTO_TRADE_MIN_CONFIDENCE` (default 46%)
- Engines triggered ≥ `AUTO_TRADE_MIN_ENGINES` (default 4)
- Daily order count < `AUTO_TRADE_MAX_DAILY_ORDERS` (default 3)
- Daily realized loss < `AUTO_TRADE_MAX_DAILY_LOSS` (default ₹10,000)
- Not already placed for this `alert_id` (dedup guard)
- `AUTO_TRADE_CONFIRMED_ONLY = True` → waits for candle-close CONFIRMED signal

### Bracket Order Logic (LIVE mode)
1. Builds Fyers option symbol (e.g. `NSE:NIFTY25APR23300CE`)
2. Uses live option LTP at candle-close as entry (not stale signal price)
3. SL and TP calculated as ATR-based offsets from fill price
4. If LIMIT entry not filled within `AUTO_TRADE_FILL_TIMEOUT_SECONDS` (30s) → re-enter at market LTP
5. Position size: `recommended_lots × AUTO_TRADE_LOT_MULTIPLIER` (or fixed `AUTO_TRADE_FIXED_LOTS`)

---

## Installation

```bash
cd nifty_trader
python -m venv venv
venv\Scripts\activate.bat           # Windows
# venv/bin/activate                 # Linux/Mac
pip install -r requirements.txt
python main.py                      # starts in mock mode (no broker needed)
```

Requires **Python 3.10+**. All dependencies pinned in `installer/requirements_pinned.txt`.

## Database Schema

SQLite file at `nifty_trader/nifty_trader.db`. Auto-created and migrated on startup — no manual SQL needed.

| Table | Purpose | Retention |
|-------|---------|-----------|
| `alerts` | Every EarlyMoveAlert + TradeSignal + ConfirmedSignal | 180 days |
| `engine_signals` | Per-engine result per tick (is_triggered, direction, strength) | 5 days |
| `ml_feature_store` | 93 ML features per signal + label after outcome | 180 days |
| `trade_outcomes` | SL/T1/T2/T3 hit tracking + realized P&L ₹ | 365 days |
| `setup_alerts` | Named setup hits per signal + propagated P&L | 180 days |
| `market_candles` | 3m/5m/15m OHLCV candles for all 4 indices | 10 days |
| `option_eod_prices` | EOD option LTPs at all strikes (for outcome labeling) | 30 days |
| `option_chain_snapshots` | Intraday OC snapshots (for P3 label priority) | 5 days |
| `s11_paper_trades` | S11 setup paper trade results | No purge |

---

## Broker Configuration (Fyers)

1. Enter App ID + Secret in the **Credentials** tab
2. Click **Generate Auth URL** → browser opens Fyers login
3. After login, copy `auth_code=XXXX` from the redirect URL
4. Paste into **Auth Code** field → **Exchange Code**
5. Token saved to `auth/fyers_token.json` (valid until midnight IST)

---

## Key Config Values (`config.py`)

```python
MIN_ENGINES_FOR_ALERT         = 3      # 3+ of 7 triggering engines → Early Move Alert (ML data collection)
MIN_ENGINES_FOR_SIGNAL        = 4      # 4+ engines required for Trade Signal (validated: 59.8% vs 38.6% at 5)
SIGNAL_MIN_VOLUME_RATIO       = 1.5    # volume must be 1.5× 20-bar average (+10% WR boost in live testing)
TRADE_SIGNAL_MIN_ADX          = 20.0   # Wilder's "trend present" threshold — below = too weak
TRADE_SIGNAL_MIN_DI_SPREAD    = 5.0    # |+DI − -DI| ≥ 5 in signal direction — directional conviction gate
TRADE_SIGNAL_REQUIRE_MTF_STRONG = True # both 5m+15m must agree (STRONG); PARTIAL/NEUTRAL blocked
ML_SIGNAL_GATE_THRESHOLD      = 0.50   # ML probability gate (Phase 2+); session-specific overrides apply
REQUIRE_TRENDING_REGIME       = True   # TRENDING regime required — single most powerful filter (55.8% WR)
MAX_VIX_FOR_SIGNAL            = 20.0   # VIX > 20 = expensive options + whippy market → block Trade Signal
AUTO_TRADE_ENABLED            = False  # OFF by default — enable via dashboard toggle
SOUND_ALERTS_ENABLED          = True
POPUP_ALERTS_ENABLED          = True
TELEGRAM_ENABLED              = False  # set via env var TELEGRAM_ENABLED=true
```

---

## Performance Notes

- Spot price: refreshed every 5 seconds (batch quotes API — one call for all 4 indices)
- Option chain: refreshed every 15 seconds (Fyers `/options-chain-v3`)
- All 7 engine evaluations: each wrapped in 5s timeout via `concurrent.futures`
- DB: SQLite with WAL mode + 60s busy_timeout; 10 composite indexes for fast queries
- ML: auto-retrains every 50 new labeled samples in background thread
- `ModelManager` singleton is thread-safe (double-checked locking)
- `expiry_calendar` cache is thread-safe (module-level `threading.Lock`)
- Alert deduplication: sound/popup/Telegram fire once per `alert_id`; resets daily at midnight
- Circuit breaker: broker API calls paused for 60s after 5 consecutive failures
- Token file: cached in memory for 60s; disk read only on cache miss or after token save
- Pre-market (before 9:00 IST): all live API calls blocked — spot falls back to `prev_day_close`

---

## Production Fixes Applied (v3.2 — April 2026)

| # | Severity | File | Fix |
|---|----------|------|-----|
| V-1 | High | fyers_adapter.py | Pre-market price mismatch — use `cp` (official NSE close) outside live hours |
| V-2 | High | data_manager.py | Bootstrap fallback chain — `prev_close` fetched first, used outside live hours |
| V-3 | High | data_manager.py | `_market_active` guard on all live API calls (9:00–15:35 IST) — stops pre-market 429 flood |
| V-4 | High | data_manager.py | Circuit breaker — opens after 5 consecutive failures, auto-resets after 60s |
| V-5 | Medium | database/manager.py | 4 new DB indexes + busy_timeout raised to 60s |
| V-6 | Medium | signal_aggregator.py | Per-engine try-catch + 5s timeout via `concurrent.futures` |
| V-7 | Medium | telegram_alert.py | Exponential backoff retry (3 attempts, 2s/4s delays) |
| V-8 | Medium | model_manager.py | Feature column validation at model load — warns on mismatch |
| V-9 | Medium | auto_labeler.py | NSE holiday check — skips records and lookahead candles on holidays |
| V-10 | Low | fyers_adapter.py | Token file 60s in-memory cache — reduces disk reads |

## Production Fixes Applied (v3.1 — March 2026)

| # | Severity | File | Fix |
|---|----------|------|-----|
| C-1 | Critical | signal_aggregator.py | ML feature key collision — explicit mapping in `_get_ml_prediction` |
| H-1 | High | setup_screener.py | None crash guard at top of `evaluate()` |
| H-2 | High | signal_aggregator.py | `SYMBOL_MAP.get()` replaces KeyError-prone direct access |
| H-3 | High | model_manager.py | Thread-safe singleton with double-checked locking |
| M-1 | Medium | ml/setups.py | Silent exception swallowed — split logging by exception type |
| M-2 | Medium | expiry_calendar.py | Thread-safe read/write with module-level `threading.Lock` |
| M-3 | Medium | outcome_tracker.py | Added `get_open_states()` public API; removed direct `_lock`/`_open` access from order_manager |
| M-4 | Medium | data_manager.py | `reconnect()` — null threads before join, timeout 4→6s |
| M-5 | Medium | alert_manager.py | Daily reset for `_dispatched_ids` to prevent unbounded growth |
| L-1 | Low | alert_manager.py | `ToastNotifier` singleton (created once in `__init__`, not per-call) |
| L-2 | Low | order_manager.py | `_get_fyers()` failure backoff (60s cooldown after failed connection) |
| L-3 | Low | signal_aggregator.py | `_diag_logged` pruned each minute to prevent unbounded set growth |
