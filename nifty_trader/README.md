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
| 7 | Market Regime | TRENDING/RANGING/VOLATILE classification via ADX + Choppiness |

### Data-Only Engines — run every tick, feed ML features only

| Engine | Why demoted | Data saved |
|--------|-------------|-----------|
| Option Chain | OI lags price — 27% WR as deciding engine | PCR, max pain, OI change, iv_rank |
| IV Expansion | IV rises AFTER big candle — lagging confirmation, 30% WR | iv_rank, avg_atm_iv, iv_change_pct |

---

## Signal Pipeline

```
Live Market Data (every 5s)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                  7 TRIGGERING ENGINES                    │
│  Compression · DI · Volume · Liquidity · Gamma · VWAP   │
│  Market Regime                                           │
│  (+ 2 data-only: Option Chain · IV Expansion)           │
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
│   └── data_manager.py          ← Live data ingestion, candle store, indicators
│
├── engines/
│   ├── compression.py           ← Engine 1: Price compression
│   ├── di_momentum.py           ← Engine 2: DI directional pressure
│   ├── option_chain.py          ← Data-only: OI/PCR analysis
│   ├── volume_pressure.py       ← Engine 3: Institutional volume
│   ├── liquidity_trap.py        ← Engine 4: Stop-hunt detection
│   ├── gamma_levels.py          ← Engine 5: MM gamma walls
│   ├── vwap_pressure.py         ← Engine 6: VWAP bounce/cross
│   ├── iv_expansion.py          ← Data-only: IV skew/change
│   ├── market_regime.py         ← Engine 7: Market classification
│   ├── mtf_alignment.py         ← MTF confidence modifier (not a gate)
│   └── signal_aggregator.py     ← Combines all engines → alerts
│
├── alerts/
│   ├── alert_manager.py         ← Dispatches: popup, sound, Telegram
│   └── telegram_alert.py        ← Telegram Bot API
│
├── database/
│   ├── models.py                ← SQLAlchemy ORM (6 tables)
│   └── manager.py               ← CRUD + auto-migration on startup
│
├── ui/
│   ├── main_window.py           ← Main window, tabs, thread bridge
│   ├── dashboard_tab.py         ← Tab 1: Live index cards + OI
│   ├── scanner_tab.py           ← Tab 2: Engine status per index
│   ├── alerts_tab.py            ← Tab 3: Alert log + trade card
│   ├── hq_trades_tab.py         ← Tab 4: Trade analytics table
│   └── credentials_tab.py       ← Tab 5: Broker auth
│
└── ml/
    ├── feature_store.py         ← 79+ FEATURE_COLUMNS + RF/XGBoost/LSTM stubs
    ├── model_manager.py         ← Train/load/predict + auto-retrain every 50 samples
    ├── auto_labeler.py          ← Background outcome labeling (runs every 15 min)
    └── outcome_tracker.py       ← SL/T1/T2/T3 level hit detection, MFE/MAE
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
MIN_ENGINES_FOR_ALERT         = 4      # 4 of 7 engines → Early Move Alert
SIGNAL_MIN_VOLUME_RATIO       = 0.8    # volume gate
TRADE_SIGNAL_MIN_ADX          = 20.0   # trend strength gate
TRADE_SIGNAL_MIN_DI_SPREAD    = 5.0    # directional conviction gate
TRADE_SIGNAL_REQUIRE_MTF_STRONG = True # both 5m+15m must agree
ML_SIGNAL_GATE_THRESHOLD      = 0.45   # ML probability gate (Phase 2+)
```

---

## Performance Notes

- Spot price: refreshed every 5 seconds
- Option chain: refreshed every 15 seconds (Fyers `/options-chain-v3`)
- All 7 engine calculations: < 50ms per tick
- DB: SQLite local file, auto-migrated on startup (no manual migrations needed)
- ML: auto-retrains every 50 new labeled samples in background thread
