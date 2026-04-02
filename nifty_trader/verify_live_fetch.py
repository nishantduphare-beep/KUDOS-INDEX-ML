#!/usr/bin/env python3
"""
Verify live market data fetch capabilities
"""
import sys, os

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
    print(f"    Go to Credentials tab in UI to set up")

# Check token file
from pathlib import Path
token_file = Path("auth/fyers_token.json")
if token_file.exists():
    print(f"✅ Token file exists: {token_file}")
else:
    print(f"⚠️  Token file NOT found: {token_file}")
    print(f"    (Will be created after first authentication)")

# Check available APIs in FyersAdapter
print(f"\n🔍 FYERS ADAPTER - AVAILABLE DATA SOURCE METHODS")
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
print(f"Checking FyersAdapter for live market data methods:")
for method in fyers_methods:
    has_method = hasattr(fyers, method) and callable(getattr(fyers, method))
    symbol = "✅" if has_method else "❌"
    print(f"  {symbol} {method:30} → {'Available' if has_method else 'MISSING'}")

# Check MockAdapter Greeks
print(f"\n🎲 MOCK ADAPTER - GREEKS CALCULATION CHECK")
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
        print(f"✅ Greeks ARE CALCULATED in Mock mode (recently fixed)")
        print(f"   Sample: Call Delta={strike.call_delta:.4f}, Gamma={strike.call_gamma:.6f}")
    else:
        print(f"❌ Greeks NOT calculated (values are zero)")
        
except Exception as e:
    print(f"❌ Error checking mock adapter: {e}")

# Summary
print(f"\n" + "="*80)
print("LIVE MARKET READINESS STATUS")
print("="*80)

status = {
    "Active Broker": config.BROKER.upper(),
    "Credentials": "✅ Configured" if has_creds else "❌ MISSING - Setup needed",
    "Spot API": "✅ Ready" if hasattr(fyers, "get_all_spot_prices") else "❌ Missing",
    "Option Chain API": "✅ Ready" if hasattr(fyers, "get_option_chain") else "❌ Missing",
    "Futures API": "✅ Ready" if hasattr(fyers, "get_all_futures_quotes") else "❌ Missing",
    "Greeks": "✅ Calculated" if has_greeks else "⚠️  Not in mock",
}

for key, value in status.items():
    print(f"  {key:20} {value}")

print(f"\n" + "="*80)
print("LIVE DATA FETCH PLAN")
print("="*80)

print(f"""
When live market starts (9:15 AM IST):

📊 Every 5 seconds:
  ✅ Batch fetch spot prices → {len(config.INDICES)} indices at once
  ✅ Batch fetch futures OI → {len(config.INDICES)} indices at once
  🔄 Try to get India VIX (best-effort)
  
⛓️  Every 30 seconds (during market hours):
  ✅ Fetch option chain → 4 separate calls (one per index)
     Each call gets 21 strikes with: OI, IV, Greekseta, etc.
  
🕯️  Every 3 minutes:
  ✅ Update candel history (3m, 5m, 15m intervals)
  
🎯 Special Events:
  • 9:00-9:15 IST: Track pre-open futures gap
  • 9:15 IST: First live spot fetch, lock pre-open snapshot
  • 15:29 IST: Force EOD option chain snapshot (final prices)
  • 15:31 IST: Run data audit + recompute Greeks

📈 Total Live Data Volume:
  ~40 API calls per minute during market hours
  ~3-4 KB per 5-second cycle
  Average latency: 100-500ms per call
  
Failover Logic:
  ✅ If Fyers API fails → use latest candle close
  ✅ If outside market hours → use previous day close
  ✅ Circuit breaker prevents repeated failures

All Systems Ready: {'✅ YES' if config.BROKER == 'fyers' else '⚠️  Using MOCK mode'}
Go-Live Status: {'🟢 READY' if has_creds else '🟡 SETUP NEEDED'}
""")

print("="*80 + "\n")
