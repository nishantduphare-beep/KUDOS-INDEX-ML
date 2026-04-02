# NiftyTrader v3 — Quick Start Guide

## Prerequisites

```bash
pip install PySide6 xgboost scikit-learn pandas numpy fyers-apiv3 sqlalchemy
```

## First Run (Mock Mode — No Broker Needed)

```bash
cd d:\nifty_trader_v3_final\nifty_trader
python main.py
```

The app starts with mock data automatically. Signals and alerts will fire using simulated price data.

## First Run with Fyers (Live Mode)

### Step 1: Set up Fyers credentials
1. Log in at https://myapi.fyers.in
2. Create an app → get App ID (e.g. `XB12345-100`) and Secret Key
3. Set Redirect URI to: `https://trade.fyers.in/api-login/redirect-uri/index.html`

### Step 2: Enter credentials in the app
1. Start the app: `python main.py`
2. Go to the **Credentials** tab
3. Enter your App ID and Secret Key
4. Click **Generate Auth URL**
5. Log in via the browser popup
6. Paste the auth code back into the app
7. Click **Save** — you'll see "Fyers active — [Your Name]"

### Step 3: Start the data feed
Click **Start** in the top toolbar. Market data begins flowing at 9:15 AM IST.

## Directory Structure

```
nifty_trader_v3_final/
  nifty_trader/          # App source code — always run from here
    main.py              # Entry point
    config.py            # All settings (edit this to tune thresholds)
    database/            # SQLite + WAL manager
    data/                # Market data adapters (Fyers, Dhan, Mock)
    engines/             # Signal detection engines (8 engines)
    ml/                  # XGBoost model + auto-labeler
    trading/             # Order manager (paper + live)
    ui/                  # PySide6 GUI
    alerts/              # Alert manager + Telegram
  scripts/               # Utility scripts (DB check, latency test)
  tests/                 # pytest test suite
  logs/                  # Auto-created log files
  TROUBLESHOOTING.md     # Common issues and fixes
```

## Key Config Settings (nifty_trader/config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `BROKER` | `"fyers"` | Active broker: fyers / dhan / mock |
| `MIN_ENGINES_FOR_SIGNAL` | `4` | Engines needed to fire a trade signal |
| `MAX_VIX_FOR_BULLISH_SIGNAL` | `25.0` | Block bullish signals above this VIX |
| `MAX_VIX_FOR_BEARISH_SIGNAL` | `28.0` | Block bearish signals above this VIX |
| `ML_CONFIDENCE_THRESHOLD` | `0.50` | Min ML probability to allow signal |
| `ML_MIN_SAMPLES_TO_ACTIVATE` | `200` | Labeled samples needed before ML trains |
| `AUTO_TRADE_ENABLED` | `False` | Enable auto order placement |
| `AUTO_TRADE_PAPER_MODE` | `False` | Paper trade instead of live orders |

## Running Tests

```bash
cd d:\nifty_trader_v3_final
pip install pytest
pytest tests/ -v
```

## Checking Database Health

```bash
cd d:\nifty_trader_v3_final\nifty_trader
python ..\scripts\check_db_integrity.py
```

## ML Training Flow

1. App runs → signals fire → `ml_feature_store` accumulates records
2. `AutoLabeler` labels outcomes every 15 minutes (ATR-based heuristic)
3. After 200 labeled records → `ModelManager` trains first XGBoost model
4. Every 50 new labeled records → automatic retraining
5. Model predictions visible in the ML tab

## Telegram Alerts Setup

Set environment variables before starting:
```bash
set TELEGRAM_ENABLED=true
set TELEGRAM_BOT_TOKEN=your_bot_token
set TELEGRAM_CHAT_ID=your_chat_id
python main.py
```

## Paper Trading

1. Go to the **Auto Trade** tab
2. Toggle **Paper Trading** ON
3. Set max daily orders (default: 3) and max daily loss (default: ₹10,000)
4. Trade signals will automatically place simulated orders
5. P&L tracked in the **Auto Trade** tab and `auto_paper_trades` DB table

## Lot Sizes (SEBI current)

| Index | Lot Size |
|-------|----------|
| NIFTY | 65 |
| BANKNIFTY | 30 |
| MIDCPNIFTY | 120 |
| SENSEX | 20 |

## Support

See `TROUBLESHOOTING.md` for common issues and fixes.
