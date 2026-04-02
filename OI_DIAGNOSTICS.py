#!/usr/bin/env python3
"""
OI Change Debugging Script
Checks why OI change is not updating live in the market dashboard.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_futures_symbols():
    """Check what futures symbol mapping looks like"""
    print("\n" + "="*70)
    print("CHECKING FUTURES SYMBOLS")
    print("="*70)
    
    import config
    from nifty_trader.data.adapters.fyers_adapter import FyersAdapter
    
    adapter = FyersAdapter()
    
    for idx in config.INDICES:
        try:
            # Access the method that generates futures symbols
            sym = adapter._near_month_futures_symbol(idx)
            print(f"✅ {idx:15} → {sym}")
        except Exception as e:
            print(f"❌ {idx:15} → Error: {e}")

def check_fyers_api_connection():
    """Check if Fyers API is connected and returning data"""
    print("\n" + "="*70)
    print("CHECKING FYERS API CONNECTION")
    print("="*70)
    
    import config
    from nifty_trader.data.adapters.fyers_adapter import FyersAdapter
    
    adapter = FyersAdapter()
    
    if not adapter._fyers:
        print("⚠️  Fyers not initialized (token may be expired)")
        print("    → This is expected if you haven't connected yet")
        return False
    
    print("✅ Fyers API initialized")
    return True

def check_futures_quotes_response():
    """Check what get_all_futures_quotes actually returns"""
    print("\n" + "="*70)
    print("CHECKING FUTURES QUOTES RESPONSE")
    print("="*70)
    
    import config
    from nifty_trader.data.adapters.fyers_adapter import FyersAdapter
    
    adapter = FyersAdapter()
    
    if not adapter._fyers:
        print("⚠️  Fyers API not connected")
        print("    Run: BROKER=fyers python nifty_trader/main.py")
        print("    Then click 'Connect' to authenticate")
        return
    
    try:
        quotes = adapter.get_all_futures_quotes()
        
        if not quotes:
            print("⚠️  No futures quotes returned")
            print("    Possible issues:")
            print("    - Market may be closed")
            print("    - Fyers API rate limit hit")
            print("    - Token expired")
            return
        
        print("✅ Futures quotes received:")
        for idx, data in quotes.items():
            oi = data.get("oi", 0)
            lp = data.get("lp", 0)
            status = "✅" if oi > 0 else "⚠️ "
            print(f"   {status} {idx:15} OI={oi:10,.0f}  LTP={lp:10,.2f}")
        
        return quotes
        
    except Exception as e:
        print(f"❌ Error fetching futures quotes: {e}")
        import traceback
        traceback.print_exc()
        return None

def check_dashboard_futures_data():
    """Check if dashboard has futures data with OI"""
    print("\n" + "="*70)
    print("CHECKING DASHBOARD FUTURES DATA")
    print("="*70)
    
    import config
    from nifty_trader.data.data_manager import DataManager
    
    dm = DataManager()
    
    print("Checking IndexState futures_df for each index:")
    
    for idx in config.INDICES:
        state = dm._states.get(idx)
        if not state:
            print(f"❌ {idx:15} → No state")
            continue
        
        futures_df = state.futures_df
        if futures_df is None or len(futures_df) == 0:
            print(f"⚠️  {idx:15} → No futures data")
            continue
        
        last_row = futures_df.iloc[-1]
        oi_val = last_row.get("oi", 0)
        status = "✅" if oi_val > 0 else "⚠️ "
        print(f"   {status} {idx:15} OI={oi_val:10,.0f}  (rows={len(futures_df)})")
        
        # Show last 3 rows to see OI pattern
        print(f"      Last 3 rows OI:")
        for i in range(max(0, len(futures_df)-3), len(futures_df)):
            row = futures_df.iloc[i]
            ts = row.get("timestamp", "N/A")
            c = row.get("close", 0)
            oi = row.get("oi", 0)
            print(f"        [{i}] {ts} close={c:,.2f} oi={oi:,.0f}")

def check_oi_change_calculation():
    """Check if OI change is being calculated correctly"""
    print("\n" + "="*70)
    print("CHECKING OI CHANGE CALCULATION")
    print("="*70)
    
    import config
    from nifty_trader.ui.dashboard_tab import _classify_oi
    from nifty_trader.data.data_manager import DataManager
    
    dm = DataManager()
    
    for idx in config.INDICES:
        state = dm._states.get(idx)
        if not state or state.futures_df is None or len(state.futures_df) < 2:
            print(f"⚠️  {idx:15} → Insufficient data")
            continue
        
        for timeframe_mins in [5, 15, 30]:
            try:
                fut_price, oi_now, oi_chg_pct, nature, color = _classify_oi(
                    state.futures_df, timeframe_mins
                )
                
                status = "✅" if abs(oi_chg_pct) > 0.01 else "⏳"
                print(f"   {status} {idx:15} {timeframe_mins}min: OI={oi_now:,.0f} "
                      f"Change={oi_chg_pct:.2f}% ({nature})")
            except Exception as e:
                print(f"   ❌ {idx:15} {timeframe_mins}min: Error: {str(e)[:40]}")

def main():
    print("\n" + "█"*70)
    print("█ OI CHANGE LIVE UPDATE DIAGNOSTICS")
    print("█"*70)
    
    print("\n1. Futures Symbols Configuration")
    check_futures_symbols()
    
    print("\n2. Fyers API Connection")
    check_fyers_api_connection()
    
    print("\n3. Futures Quotes Response")
    quotes = check_futures_quotes_response()
    
    if quotes:
        print("\n4. Dashboard Futures Data State")
        check_dashboard_futures_data()
        
        print("\n5. OI Change Calculation")
        check_oi_change_calculation()
    
    print("\n" + "="*70)
    print("DIAGNOSIS COMPLETE")
    print("="*70)
    print("""
WHAT TO CHECK:

If OI is showing as "--":
  ✓ Make sure market hours are active (9:15-15:30 IST)
  ✓ Check if Fyers token is valid (should say "Expires XX Apr 00:00 IST")
  ✓ Look for any rate-limit or API errors in the app logs

If OI is showing but no change:
  ✓ OI might be exact integer (0 change) during quiet periods
  ✓ Need at least 2 data points N minutes apart to show change
  ✓ Check if database is saving OI values to futures_candles table

Issue: Fyers API not returning OI in quotes?
  → OI field name might be different than "oi"
  → Check Fyers API v3 documentation for correct field name
  → May need to update the field extraction in fyers_adapter.py
    """)

if __name__ == "__main__":
    main()
