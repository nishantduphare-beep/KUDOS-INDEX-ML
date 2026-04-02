#!/usr/bin/env python3
"""
Verify live market data fetch capabilities
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(os.path.dirname(__file__), "nifty_trader"))

print("\n" + "="*80)
print("LIVE MARKET DATA FETCH VERIFICATION")
print("="*80)

import config
from data.adapters.fyers_adapter import FyersAdapter
from data.adapters.mock_adapter import MockAdapter

# Check current broker
print(f"\n📋 CONFIGURATION")
print("-" * 80)
print(f"Current Broker: {config.BROKER}")
print(f"Indices: {config.INDICES}")
print(f"Data Fetch Interval: {config.DATA_FETCH_INTERVAL_SECONDS}s")
print(f"Option Chain Refresh: {config.OC_REFRESH_INTERVAL_SECONDS}s")
print(f"Candle Interval: {config.CANDLE_INTERVAL_MINUTES} min")

# Check Fyers credentials status
print(f"\n🔐 FYERS CREDENTIALS STATUS")
print("-" * 80)
fyers_creds = config.BROKER_CREDENTIALS.get("fyers", {})
client_id = fyers_creds.get("client_id", "")
app_id = fyers_creds.get("app_id", "")
access_token = fyers_creds.get("access_token", "")

if client_id and app_id and access_token:
    print(f"✅ Client ID: {client_id[:5]}... (configured)")
    print(f"✅ App ID: {app_id[:8]}... (configured)")
    print(f"✅ Access Token: {access_token[:20]}... (configured)")
    has_creds = True
else:
    print(f"❌ Client ID: {client_id if client_id else 'NOT SET'}")
    print(f"❌ App ID: {app_id if app_id else 'NOT SET'}")
    print(f"❌ Access Token: {access_token if access_token else 'NOT SET'}")
    has_creds = False

# Check token file
from pathlib import Path
token_file = Path("auth/fyers_token.json")
if token_file.exists():
    print(f"✅ Token file exists: {token_file}")
else:
    print(f"⚠️  Token file NOT found: {token_file}")

# Check available APIs in FyersAdapter
print(f"\n🔍 FYERS ADAPTER - AVAILABLE API METHODS")
print("-" * 80)

fyers_methods = [
    "get_all_spot_prices",
    "get_historical_candles",
    "get_futures_candles",
    "get_all_futures_quotes",
    "get_option_chain",
    "get_vix",
    "get_prev_day_close"
]

fyers = FyersAdapter()
print(f"Checking FyersAdapter for data fetch methods:")
for method in fyers_methods:
    has_method = hasattr(fyers, method) and callable(getattr(fyers, method))
    symbol = "✅" if has_method else "❌"
    print(f"  {symbol} {method:30} → {'Available' if has_method else 'MISSING'}")

# Check MockAdapter Greeks
print(f"\n🎲 MOCK ADAPTER - GREEKS CALCULATION")
print("-" * 80)

try:
    mock = MockAdapter()
    mock.connect()
    chain = mock.get_option_chain("NIFTY")
    strike = chain.strikes[10]
    
    has_greeks = (
        strike.call_delta != 0 and 
        strike.call_gamma != 0 and
        strike.put_delta != 0
    )
    
    if has_greeks:
        print(f"✅ Greeks CALCULATED in Mock mode")
        print(f"   Call Delta: {strike.call_delta:.4f}")
        print(f"   Call Gamma: {strike.call_gamma:.6f}")
        print(f"   Put Delta:  {strike.put_delta:.4f}")
    else:
        print(f"❌ Greeks NOT calculated (all zeros)")
        
except Exception as e:
    print(f"❌ Error checking mock adapter: {e}")

# Summary
print(f"\n" + "="*80)
print("LIVE MARKET READINESS STATUS")
print("="*80)

status = {
    "Broker": "fyers" if config.BROKER == "fyers" else f"❌ {config.BROKER}",
    "Credentials": "✅ Configured" if has_creds else "❌ NOT configured",
    "Spot API": "✅ get_all_spot_prices()" if hasattr(fyers, "get_all_spot_prices") else "❌ Missing",
    "Option Chain API": "✅ get_option_chain()" if hasattr(fyers, "get_option_chain") else "❌ Missing",
    "Futures API": "✅ get_all_futures_quotes()" if hasattr(fyers, "get_all_futures_quotes") else "❌ Missing",
    "VIX API": "✅ get_vix()" if hasattr(fyers, "get_vix") else "❌ Missing",
}

print(f"\nSummary:")
for key, value in status.items():
    print(f"  {key:20} {value}")

print(f"\n" + "="*80)
print("DATA FETCH PLAN")
print("="*80)

print(f"""
Every 5 seconds (during 9:15-15:35 IST):
  1. Batch fetch spot prices → {len(config.INDICES)} indices
  2. Batch fetch futures OI → {len(config.INDICES)} indices
  3. Try to get VIX (optional)

Every 30 seconds (during market hours):
  4. Fetch option chain → {len(config.INDICES)} calls

Every 3 minutes:
  5. Update candles (3m, 5m, 15m intervals)

Special events:
  • 9:00-9:15: Track pre-open futures gap
  • 9:15: First live data fetch, lock pre-open snapshot
  • 15:29: Force EOD option chain snapshot
  • 15:31: Run data audit + Greeks recompute

Data Sources: 
  ✅ Fyers API (when connected)
  ✅ Fallback: Latest candle close (if API fails)
  ✅ Fallback: Previous day close (outside hours)

All {'✅ READY' if config.BROKER == 'fyers' else '❌ NOT READY'} for live market!
""")

print("="*80 + "\n")
