# NiftyTrader — VPS Developer Setup Guide

> For: Developers deploying NiftyTrader on a remote Linux VPS
> App type: Python + PySide6 desktop application (headless-capable via virtual display)
> Tested on: Ubuntu 22.04 LTS

---

## Table of Contents

1. [VPS Requirements](#1-vps-requirements)
2. [System Dependencies](#2-system-dependencies)
3. [Python Setup](#3-python-setup)
4. [App Installation](#4-app-installation)
5. [Fyers Broker Setup](#5-fyers-broker-setup)
6. [Running Headless (No Monitor)](#6-running-headless-no-monitor)
7. [Auto-Start on Boot (systemd)](#7-auto-start-on-boot-systemd)
8. [Remote Access — Viewing the UI](#8-remote-access--viewing-the-ui)
9. [Logs and Monitoring](#9-logs-and-monitoring)
10. [Keeping the App Running](#10-keeping-the-app-running)
11. [Updating the App](#11-updating-the-app)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. VPS Requirements

### Minimum Specs
| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 10 GB SSD | 20 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Python | 3.10+ | 3.11 |
| Network | 10 Mbps stable | 50 Mbps (option chain data is ~200KB/request) |

### Timing Requirements
- VPS clock **must be accurate** — NiftyTrader uses `datetime.now()` for market hours logic
- IST is UTC+5:30; Fyers API gates data strictly by IST time
- **Strongly recommended**: sync NTP on the VPS (see below)

### Ports Required
| Port | Purpose |
|------|---------|
| 22 | SSH access |
| None | App is desktop-only; no inbound port needed unless you add a web layer |

---

## 2. System Dependencies

```bash
# Update package list
sudo apt update && sudo apt upgrade -y

# Python build dependencies
sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    build-essential git curl wget

# PySide6 / Qt6 runtime libraries (required even headless)
sudo apt install -y \
    libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 \
    libxcb-xfixes0 libxcb1 libx11-6 libx11-xcb1 \
    libfontconfig1 libfreetype6

# Virtual display (Xvfb) — required to run PySide6 without a physical monitor
sudo apt install -y xvfb x11-utils

# Audio libraries (for sound alerts — skip if not needed)
sudo apt install -y libasound2 libpulse0

# NTP sync — keeps VPS clock accurate (critical for IST market hour logic)
sudo apt install -y ntp
sudo systemctl enable ntp
sudo systemctl start ntp

# Verify time sync
timedatectl status
# Should show: System clock synchronized: yes
```

---

## 3. Python Setup

```bash
# Create a dedicated user for the app (optional but recommended)
sudo adduser niftytrader --disabled-password --gecos ""
sudo su - niftytrader

# Clone the repository
git clone https://github.com/nishantduphare-beep/KUDOS-INDEX-ML.git
cd KUDOS-INDEX-ML

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r nifty_trader/requirements.txt
```

### Verify Installation

```bash
cd nifty_trader
python -c "from PySide6.QtWidgets import QApplication; print('PySide6 OK')"
python -c "import fyers_apiv3; print('Fyers SDK OK')"
python -c "import xgboost; print('XGBoost OK')"
```

---

## 4. App Installation

### Directory Layout After Clone

```
KUDOS-INDEX-ML/
├── nifty_trader/           ← main application (run from here)
│   ├── main.py             ← entry point
│   ├── config.py           ← all settings
│   ├── requirements.txt
│   ├── auth/               ← created automatically; stores fyers_token.json
│   ├── logs/               ← created automatically; daily log files
│   ├── models/             ← created automatically; ML model files
│   └── nifty_trader.db     ← SQLite DB (created on first run)
├── DOCUMENTATION.md
├── VPS_SETUP_GUIDE.md      ← this file
└── NiftyTrader_Setup_Guide.md
```

### Environment Variables (Optional)

Set these in the shell or in the systemd service file:

```bash
export BROKER=fyers                        # fyers | dhan | mock
export FYERS_CLIENT_ID=XB12345
export FYERS_APP_ID=XB12345-100
export FYERS_SECRET_KEY=your_secret
export TELEGRAM_ENABLED=true               # optional
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
export DB_PATH=/home/niftytrader/KUDOS-INDEX-ML/nifty_trader/nifty_trader.db
```

Alternatively, credentials can be entered via the **Credentials tab** in the UI and are saved to `auth/credentials.json` for subsequent launches.

---

## 5. Fyers Broker Setup

NiftyTrader uses Fyers OAuth 2.0. The token expires at midnight IST daily and must be refreshed each trading day.

### First-Time Auth (Do This Locally, Not on VPS)

The OAuth flow requires a browser. Do this on your local machine:

1. Install the app locally
2. Open the **Credentials** tab
3. Enter App ID + Secret → click **Generate Auth URL**
4. Browser opens → log in to Fyers → approve access
5. Copy the `auth_code=XXXX` from the redirect URL
6. Paste into the **Auth Code** field → click **Exchange Code**
7. Token is saved to `auth/fyers_token.json`

### Transfer Token to VPS

```bash
# Copy the token file to VPS after local auth
scp auth/fyers_token.json niftytrader@YOUR_VPS_IP:/home/niftytrader/KUDOS-INDEX-ML/nifty_trader/auth/
```

### Daily Token Refresh

Fyers tokens expire at midnight IST. Options:

**Option A — Manual daily refresh** (simple)
- SSH in each morning, run the auth flow via VNC/X11 forwarding
- Paste the new auth code via CLI (see `fyers_adapter.py:exchange_auth_code()`)

**Option B — Automate via Fyers API v3 refresh** (if Fyers supports it for your app type)
- Fyers API v3 supports token refresh for some app types
- Check Fyers developer docs for your specific app configuration

**Option C — CLI auth helper** (no UI needed)
```bash
cd /home/niftytrader/KUDOS-INDEX-ML/nifty_trader
source ../venv/bin/activate
python -c "
from data.adapters.fyers_adapter import FyersAdapter
a = FyersAdapter()
url = a.generate_auth_url()
print('Open this URL in browser:', url)
code = input('Paste auth_code here: ')
a.exchange_auth_code(code)
print('Token saved.')
"
```

---

## 6. Running Headless (No Monitor)

PySide6 requires a display. On a VPS without a monitor, use Xvfb (virtual framebuffer):

### Manual Start

```bash
# Start virtual display on display :99
Xvfb :99 -screen 0 1280x800x24 &
export DISPLAY=:99

# Run the app
cd /home/niftytrader/KUDOS-INDEX-ML/nifty_trader
source ../venv/bin/activate
BROKER=fyers python main.py
```

### Check If Running

```bash
ps aux | grep main.py       # check app process
ps aux | grep Xvfb          # check virtual display
```

---

## 7. Auto-Start on Boot (systemd)

Create a systemd service so the app restarts automatically after VPS reboots or crashes.

### Step 1 — Create the Xvfb service

```bash
sudo nano /etc/systemd/system/xvfb-niftytrader.service
```

```ini
[Unit]
Description=Xvfb virtual display for NiftyTrader
After=network.target

[Service]
Type=forking
User=niftytrader
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x800x24
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Step 2 — Create the NiftyTrader service

```bash
sudo nano /etc/systemd/system/niftytrader.service
```

```ini
[Unit]
Description=NiftyTrader Intelligence System
After=network.target xvfb-niftytrader.service
Requires=xvfb-niftytrader.service

[Service]
Type=simple
User=niftytrader
WorkingDirectory=/home/niftytrader/KUDOS-INDEX-ML/nifty_trader
Environment="DISPLAY=:99"
Environment="BROKER=fyers"
Environment="TELEGRAM_ENABLED=true"
Environment="TELEGRAM_BOT_TOKEN=your_token_here"
Environment="TELEGRAM_CHAT_ID=your_chat_id_here"
ExecStart=/home/niftytrader/KUDOS-INDEX-ML/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/niftytrader/KUDOS-INDEX-ML/nifty_trader/logs/systemd.log
StandardError=append:/home/niftytrader/KUDOS-INDEX-ML/nifty_trader/logs/systemd.log

[Install]
WantedBy=multi-user.target
```

### Step 3 — Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable xvfb-niftytrader
sudo systemctl enable niftytrader
sudo systemctl start xvfb-niftytrader
sudo systemctl start niftytrader

# Check status
sudo systemctl status niftytrader
```

---

## 8. Remote Access — Viewing the UI

Since the app runs on a virtual display, you need one of these to see the UI:

### Option A — VNC (Recommended for daily monitoring)

```bash
# Install TigerVNC on VPS
sudo apt install -y tigervnc-standalone-server tigervnc-common

# Start VNC server (connects to the same Xvfb display)
vncserver :1 -geometry 1280x800 -depth 24

# On your local machine — connect via VNC client
# Address: YOUR_VPS_IP:5901
# Use: RealVNC Viewer, TigerVNC Viewer, or Remmina
```

### Option B — X11 Forwarding over SSH (Occasional access)

```bash
# On your local machine (requires X11 client — XQuartz on Mac, VcXsrv on Windows)
ssh -X niftytrader@YOUR_VPS_IP

# Then run the app — window appears on your local screen
cd KUDOS-INDEX-ML/nifty_trader
source ../venv/bin/activate
BROKER=fyers python main.py
```

### Option C — Screenshots via scrot (Quick status check)

```bash
# Install scrot
sudo apt install -y scrot

# Take a screenshot of the virtual display
DISPLAY=:99 scrot /tmp/niftytrader_status.png

# Copy to local machine
scp niftytrader@YOUR_VPS_IP:/tmp/niftytrader_status.png ./
```

---

## 9. Logs and Monitoring

### Application Logs

```bash
# Today's log
tail -f /home/niftytrader/KUDOS-INDEX-ML/nifty_trader/logs/niftytrader_$(date +%Y%m%d).log

# Last 100 lines
tail -100 /home/niftytrader/KUDOS-INDEX-ML/nifty_trader/logs/niftytrader_$(date +%Y%m%d).log

# Search for errors
grep -i "error\|warning\|429\|failed" logs/niftytrader_$(date +%Y%m%d).log

# Search for signals generated today
grep "TRADE_SIGNAL\|EARLY_MOVE" logs/niftytrader_$(date +%Y%m%d).log
```

### systemd Service Logs

```bash
sudo journalctl -u niftytrader -f          # follow live
sudo journalctl -u niftytrader --since today
sudo journalctl -u niftytrader -n 100      # last 100 lines
```

### Key Log Lines to Watch

| Log message | Meaning |
|-------------|---------|
| `DataManager running` | App connected and scanning |
| `Bootstrap NIFTY: spot from API` | Startup price source (API / prev_close / candle) |
| `CircuitBreaker OPEN` | Broker API failing — check token/connection |
| `Fyers token expired` | Need to re-run OAuth flow |
| `TRADE_SIGNAL` | Signal generated |
| `Telegram send failed after all retries` | Check TELEGRAM_BOT_TOKEN and CHAT_ID |
| `Feature column mismatch detected` | ML model needs retraining |

---

## 10. Keeping the App Running

### Automatic Restart
The systemd service restarts the app automatically on crash (`Restart=on-failure`).

### Daily Token Renewal Reminder
Fyers tokens expire at midnight IST. Set up a Telegram message or cron job to remind you:

```bash
# Cron job to send a Telegram reminder at 8:30 AM IST daily
crontab -e
# Add:
0 3 * * 1-5 curl -s "https://api.telegram.org/botYOUR_TOKEN/sendMessage?chat_id=YOUR_CHAT_ID&text=NiftyTrader+token+renewal+needed" > /dev/null
# (8:30 AM IST = 3:00 AM UTC, weekdays only)
```

### Database Backup
SQLite DB is a single file. Back it up daily:

```bash
# Add to crontab — backup DB at 4:00 AM IST (22:30 UTC) daily
30 22 * * * cp /home/niftytrader/KUDOS-INDEX-ML/nifty_trader/nifty_trader.db \
    /home/niftytrader/backups/niftytrader_$(date +%Y%m%d).db

# Create backup directory
mkdir -p /home/niftytrader/backups
```

---

## 11. Updating the App

```bash
# SSH into VPS
ssh niftytrader@YOUR_VPS_IP

# Stop the service
sudo systemctl stop niftytrader

# Pull latest code
cd /home/niftytrader/KUDOS-INDEX-ML
git pull origin main

# Install any new dependencies
source venv/bin/activate
pip install -r nifty_trader/requirements.txt

# Restart the service
sudo systemctl start niftytrader
sudo systemctl status niftytrader
```

The database auto-migrates on startup — no manual SQL needed for schema changes.

---

## 12. Troubleshooting

### App won't start — "cannot connect to X server"
```bash
# Check Xvfb is running
ps aux | grep Xvfb

# Start it manually
Xvfb :99 -screen 0 1280x800x24 &
export DISPLAY=:99
python main.py
```

### App shows "Broker connection failed"
```bash
# Check token file exists and is today's
cat nifty_trader/auth/fyers_token.json | python3 -m json.tool
# Look at "expires_at" — must be tonight's midnight IST

# Re-run OAuth if expired (see Section 5)
```

### 429 errors flooding logs after 9:00 AM
```bash
# This means the _market_active guard is not triggering correctly
# Check VPS system time
date
timedatectl

# Verify it matches IST
TZ=Asia/Kolkata date
```

### High RAM usage after several days
```bash
# Check process RAM
ps aux --sort=-%mem | head -5

# SQLite WAL file growing too large — flush it
sqlite3 nifty_trader/nifty_trader.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### PySide6 import error — missing Qt libraries
```bash
# Re-run the system dependency install (Section 2)
sudo apt install -y libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 libxcb1

# Test
python -c "from PySide6.QtWidgets import QApplication"
```

### Telegram alerts not arriving
```bash
# Test Telegram manually
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
    -d "chat_id=$TELEGRAM_CHAT_ID&text=NiftyTrader+test"

# If curl works but app doesn't send — check TELEGRAM_ENABLED=true in service file
```

---

## Quick Reference — Daily Operations

```bash
# Check app is running
sudo systemctl status niftytrader

# View today's log
tail -50 ~/KUDOS-INDEX-ML/nifty_trader/logs/niftytrader_$(date +%Y%m%d).log

# Restart app (e.g. after token refresh)
sudo systemctl restart niftytrader

# Stop app
sudo systemctl stop niftytrader

# Take UI screenshot
DISPLAY=:99 scrot /tmp/ui.png && scp niftytrader@VPS_IP:/tmp/ui.png ./

# Update app
cd ~/KUDOS-INDEX-ML && git pull && sudo systemctl restart niftytrader
```
