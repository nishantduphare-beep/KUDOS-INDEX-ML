# NiftyTrader Intelligence System

A local, desktop-based intraday trading intelligence application for Indian index options.
Built with Python + PySide6. Runs entirely on your machine — no browser, no cloud.

---

## Engines

### Triggering Engines (6) — vote toward alert threshold

| # | Engine | What it detects |
|---|--------|----------------|
| 1 | Compression | Price coiling before expansion (range/ATR contraction) |
| 2 | DI Momentum | Directional pressure before ADX confirms (+DI/-DI slope) |
| 3 | Volume Pressure | Institutional accumulation/distribution (volume spike pattern) |
| 4 | Liquidity Trap | Stop-hunt sweep + reversal (wick rejection) |
| 5 | Gamma Levels | MM delta-hedge walls and gamma flip (OI-based) |
| 6 | VWAP Pressure | Price bouncing/crossing VWAP with volume (institutional anchor) |

### Data-Only Engines — run every tick, feed ML features, do not vote

| Engine | Why data-only | Data saved |
|--------|--------------|-----------|
| Option Chain | OI lags price — 27% WR as deciding engine | PCR, max pain, OI change, iv_rank |
| IV Expansion | IV rises AFTER big candle — lagging confirmation, 30% WR | iv_rank, avg_atm_iv, iv_change_pct |
| Market Regime | Context classifier, not a directional trigger | regime (TRENDING/RANGING/VOLATILE), adx, atr_ratio |

---

## Signal Pipeline

```
Live Market Data (every 5s)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                  6 TRIGGERING ENGINES                    │
│  Compression · DI · Volume · Liquidity · Gamma · VWAP   │
│  (+ 3 data-only: Option Chain · IV Expansion · Regime)  │
└─────────────────────────────────────────────────────────┘
        │
        ▼  ≥ 4 engines align
┌──────────────────────┐
│   EARLY MOVE ALERT   │  → Sound + Popup + Telegram
│   Direction + Score  │  → Logged to DB + ML store
└──────────────────────┘
        │
        ▼  + all quality gates pass
┌──────────────────────────────────────────────────┐
│    TRADE SIGNAL (pending candle close)            │
│  Quality gates:                                   │
│  ├─ Compression breakout confirmed                │
│  ├─ Volume ≥ 0.8× average                        │
│  ├─ PCR ≥ 0.7                                    │
│  ├─ ADX ≥ 20 on 3m candle                        │
│  ├─ |DI spread| ≥ 5 in signal direction           │
│  ├─ MTF STRONG (both 5m+15m agree)               │
│  └─ ML probability ≥ 0.45 (if model active)      │
└──────────────────────────────────────────────────┘
        │
        ▼  next candle open
┌──────────────────────┐
│  CONFIRMED SIGNAL    │  → Instrument suggestion
│  Entry / SL / T1/T2/T3│  → Outcome tracking begins
└──────────────────────┘
        │
        ▼  SL / T1 / T2 / T3 hit or EOD
┌──────────────────────┐
│  OUTCOME LABELED     │  → P&L in ₹ recorded to DB
│  ML training sample  │  → Auto-retrain triggered
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
│   │   ├── fyers_adapter.py     ← Fyers API (primary broker)
│   │   ├── dhan_adapter.py      ← Dhan adapter
│   │   └── mock_adapter.py      ← Synthetic OHLCV for testing
│   ├── data_manager.py          ← Live data ingestion, candle store, indicators
│   ├── expiry_calendar.py       ← Broker-driven expiry dates (thread-safe cache)
│   ├── event_calendar.py        ← Economic event calendar
│   ├── event_updater.py         ← Background event data fetcher
│   ├── structures.py            ← Candle / tick data structures
│   └── base_api.py              ← Broker adapter base class
│
├── engines/
│   ├── compression.py           ← Engine 1: Price compression
│   ├── di_momentum.py           ← Engine 2: DI directional pressure
│   ├── volume_pressure.py       ← Engine 3: Institutional volume
│   ├── liquidity_trap.py        ← Engine 4: Stop-hunt detection
│   ├── gamma_levels.py          ← Engine 5: MM gamma walls
│   ├── vwap_pressure.py         ← Engine 6: VWAP bounce/cross
│   ├── option_chain.py          ← Data-only: OI/PCR analysis
│   ├── iv_expansion.py          ← Data-only: IV skew/change
│   ├── market_regime.py         ← Data-only: Market classification
│   ├── mtf_alignment.py         ← MTF confidence modifier
│   ├── setup_screener.py        ← Named setup pattern matching
│   └── signal_aggregator.py     ← Combines all engines → alerts
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
│   ├── main_window.py           ← Main window, tabs, thread bridge
│   ├── dashboard_tab.py         ← Tab 1: Live index cards + OI
│   ├── scanner_tab.py           ← Tab 2: Engine status per index
│   ├── alerts_tab.py            ← Tab 3: Alert log + trade card
│   ├── hq_trades_tab.py         ← Tab 4: Trade analytics table
│   ├── setup_tab.py             ← Tab 5: Named setup performance (win rate, P&L)
│   ├── options_flow_tab.py      ← Tab 6: Options flow / OI analysis
│   ├── ledger_tab.py            ← Tab 7: Trade ledger / P&L history
│   ├── ml_report_widget.py      ← ML model report widget
│   └── credentials_tab.py       ← Broker auth
│
└── ml/
    ├── feature_store.py         ← 79+ FEATURE_COLUMNS definitions
    ├── model_manager.py         ← Train/load/predict + auto-retrain (thread-safe singleton)
    ├── setups.py                ← 23 named setup definitions (condition + metadata)
    ├── historical_trainer.py    ← Fetch historical Fyers data → build ML training set
    ├── auto_labeler.py          ← Background outcome labeling (runs every 15 min)
    └── outcome_tracker.py       ← SL/T1/T2/T3 level hit detection, MFE/MAE, P&L ₹
```

---

## ML Feature Groups (79+ features)

| Group | Key features |
|-------|-------------|
| Engine outputs | compression_ratio, adx, di_spread, plus/minus_di, pcr, volume_ratio, gamma_flip |
| VWAP | dist_to_vwap_pct, vwap_bounce, vwap_cross_up/down, vwap_rejection, vwap_vol_ratio |
| Engine triggers | compression/di/volume/liquidity/gamma/vwap/iv/oc_triggered |
| MTF DI slopes | plus/minus_di_slope_5m/15m, di_reversal_5m/15m/both |
| Price structure | struct_5m, struct_15m, struct_5m/15m_aligned, struct_both_aligned |
| Time context | mins_since_open, session, is_expiry, day_of_week, dte |
| Price context | spot_vs_prev_pct, atr_pct_spot, chop, efficiency_ratio, gap_pct |
| Candle patterns | prev_body_ratio, consec_bull/bear, range_expansion |
| OI & Futures | futures_oi_m, futures_oi_chg_pct, atm_oi_ratio |
| VIX | vix, vix_high |
| Signal identity | direction_encoded, index_encoded, is_trade_signal |

**Feature key collision fix (v3.1):** `_get_ml_prediction` now uses an explicit per-engine mapping
identical to `_save_ml_features`. Three formerly silent collisions resolved: `iv_rank`
(option_chain vs iv_expansion), `volume_ratio` (volume_pressure vs liquidity_trap),
`adx` (di_momentum vs market_regime). Train and predict now use the same feature values.

---

## P&L Tracking

Outcomes are tracked in rupees using `lot_size × premium_move`:

| Index | Lot size | Typical premium move per point |
|-------|----------|-------------------------------|
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

| Index | Expiry day |
|-------|-----------|
| NIFTY | Tuesday |
| BANKNIFTY | Wednesday |
| MIDCPNIFTY | Monday |
| FINNIFTY | Tuesday |
| SENSEX | Thursday |
| BANKEX | Monday |

Hardcoded weekday math is only used as a cold-start fallback before the first broker
connection. After connection, all expiry logic is broker-driven.

---

## Auto Trading

Controlled by `config.AUTO_TRADE_MODE`:

| Mode | Behavior |
|------|---------|
| `"OFF"` | No orders placed (default) |
| `"PAPER"` | Simulated fills at signal price; P&L tracked without real orders |
| `"LIVE"` | Real bracket orders via Fyers API |

PAPER mode tracks entry, SL, T1/T2/T3 levels and marks them hit via `OutcomeTracker`.
LIVE mode places bracket orders via `order_manager.py` → `FyersAdapter`.

---

## Installation

```bash
cd nifty_trader
python -m venv venv
venv\Scripts\activate.bat      # Windows
pip install -r requirements.txt
python main.py                  # starts in mock mode by default
```

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
MIN_ENGINES_FOR_ALERT         = 4      # 4 of 6 triggering engines → Early Move Alert
SIGNAL_MIN_VOLUME_RATIO       = 0.8    # volume gate
TRADE_SIGNAL_MIN_ADX          = 20.0   # trend strength gate
TRADE_SIGNAL_MIN_DI_SPREAD    = 5.0    # directional conviction gate
TRADE_SIGNAL_REQUIRE_MTF_STRONG = True # both 5m+15m must agree
ML_SIGNAL_GATE_THRESHOLD      = 0.45   # ML probability gate (Phase 2+)
AUTO_TRADE_MODE               = "OFF"  # "OFF" | "PAPER" | "LIVE"
SOUND_ALERTS_ENABLED          = True
POPUP_ALERTS_ENABLED          = True
TELEGRAM_ENABLED              = False
```

---

## Performance Notes

- Spot price: refreshed every 5 seconds
- Option chain: refreshed every 15 seconds (Fyers `/options-chain-v3`)
- All 6 triggering engine calculations: < 50ms per tick
- DB: SQLite local file, auto-migrated on startup (no manual migrations needed)
- ML: auto-retrains every 50 new labeled samples in background thread
- `ModelManager` singleton is thread-safe (double-checked locking)
- `expiry_calendar` cache is thread-safe (module-level `threading.Lock`)
- Alert deduplication: sound/popup/Telegram fire once per `alert_id`; resets daily

---

## Production Fixes Applied (v3.1)

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
