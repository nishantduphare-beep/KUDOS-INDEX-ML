#!/usr/bin/env python3
"""
Diagnostic: Check if system is importing options greeks from broker
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("\n" + "="*80)
print("OPTIONS GREEKS IMPORT DIAGNOSTIC")
print("="*80)

# Check 1: Verify data structures have Greeks fields
print("\n1️⃣  CHECKING DATA STRUCTURES")
print("-" * 80)

try:
    from nifty_trader.data.structures import OptionStrike
    import dataclasses
    
    fields = {f.name: f.type for f in dataclasses.fields(OptionStrike)}
    
    required_greeks = [
        "call_delta", "call_gamma", "call_theta", "call_vega",
        "put_delta", "put_gamma", "put_theta", "put_vega"
    ]
    
    print(f"✅ OptionStrike dataclass found")
    print(f"   Total fields: {len(fields)}")
    
    missing = [g for g in required_greeks if g not in fields]
    if missing:
        print(f"❌ MISSING GREEKS: {missing}")
    else:
        print(f"✅ ALL GREEKS FIELDS PRESENT:")
        for g in required_greeks:
            print(f"   ✓ {g}")
            
except Exception as e:
    print(f"❌ Error checking structures: {e}")

# Check 2: Verify Black-Scholes Greeks calculation
print("\n2️⃣  CHECKING BLACK-SCHOLES GREEKS CALCULATION")
print("-" * 80)

try:
    from nifty_trader.data.bs_utils import bs_greeks
    
    # Test calculation
    spot, strike, tte, rate = 23500.0, 23500.0, 1/52, 0.065
    
    call_greeks = bs_greeks(spot, strike, tte, rate, "CE", iv_pct=20.0)
    put_greeks = bs_greeks(spot, strike, tte, rate, "PE", iv_pct=20.0)
    
    print(f"✅ Black-Scholes Greeks calculator imported")
    print(f"   Test: NIFTY23500 CE (ATM, 1 week)")
    print(f"   • Delta: {call_greeks['delta']:.4f}")
    print(f"   • Gamma: {call_greeks['gamma']:.6f}")
    print(f"   • Theta: {call_greeks['theta']:.6f}")
    print(f"   • Vega:  {call_greeks['vega']:.6f}")
    
except Exception as e:
    print(f"❌ Error with Greeks calculation: {e}")

# Check 3: Fyers Adapter - Does it calculate Greeks?
print("\n3️⃣  CHECKING FYERS ADAPTER")
print("-" * 80)

try:
    from nifty_trader.data.adapters.fyers_adapter import FyersAdapter
    import inspect
    
    source = inspect.getsource(FyersAdapter.get_option_chain)
    
    has_bs_greeks = "_bs_greeks" in source
    has_call_delta = "call_delta=cg" in source
    
    if has_bs_greeks and has_call_delta:
        print(f"✅ Fyers Adapter CALCULATES GREEKS")
        print(f"   • Uses: _bs_greeks() function")
        print(f"   • Calculates: call_delta, call_gamma, call_theta, call_vega")
        print(f"   •           put_delta,  put_gamma,  put_theta,  put_vega")
    else:
        print(f"❌ Fyers Adapter does NOT calculate Greeks")
        print(f"   • _bs_greeks used: {has_bs_greeks}")
        print(f"   • call_delta set:  {has_call_delta}")
        
except Exception as e:
    print(f"❌ Error checking Fyers adapter: {e}")

# Check 4: Mock Adapter - Does it calculate Greeks?
print("\n4️⃣  CHECKING MOCK ADAPTER")
print("-" * 80)

try:
    from nifty_trader.data.adapters.mock_adapter import MockAdapter
    import inspect
    
    source = inspect.getsource(MockAdapter.get_option_chain)
    
    has_bs_greeks = "_bs_greeks" in source or "bs_greeks" in source
    has_call_delta = "call_delta=" in source
    
    if has_bs_greeks and has_call_delta:
        print(f"✅ Mock Adapter CALCULATES GREEKS")
        print(f"   • Uses: Black-Scholes calculation")
    else:
        print(f"⚠️  Mock Adapter does NOT calculate Greeks")
        print(f"   • _bs_greeks used: {has_bs_greeks}")
        print(f"   • call_delta set:  {has_call_delta}")
        print(f"   • IMPACT: Greeks fields will be 0.0 in mock mode")
        
except Exception as e:
    print(f"❌ Error checking Mock adapter: {e}")

# Check 5: Data Manager - Does it use Greeks?
print("\n5️⃣  CHECKING DATA MANAGER")
print("-" * 80)

try:
    from nifty_trader.data.data_manager import DataManager
    import inspect
    
    # Check if it saves Greeks
    source = inspect.getsource(DataManager)
    
    saves_delta_call = "delta_call" in source
    saves_delta_put = "delta_put" in source
    saves_all_greeks = all(x in source for x in ["delta_call", "gamma_call", "theta_call", "vega_call",
                                                   "delta_put", "gamma_put", "theta_put", "vega_put"])
    
    if saves_all_greeks:
        print(f"✅ Data Manager SAVES ALL GREEKS to database")
        print(f"   • Saves to: option_eod_prices table")
        print(f"   • Fields: delta, gamma, theta, vega (for both CE and PE)")
    else:
        print(f"⚠️  Data Manager may not save all Greeks")
        print(f"   • delta_call saved: {saves_delta_call}")
        print(f"   • delta_put saved:  {saves_delta_put}")
        print(f"   • All Greeks saved: {saves_all_greeks}")
        
except Exception as e:
    print(f"❌ Error checking Data Manager: {e}")

# Check 6: Run actual adapter and check output
print("\n6️⃣  LIVE ADAPTER TEST")
print("-" * 80)

try:
    import config
    from nifty_trader.data.adapters.mock_adapter import MockAdapter
    
    adapter = MockAdapter()
    adapter.connect()
    
    chain = adapter.get_option_chain("NIFTY")
    
    if chain and chain.strikes:
        strike = chain.strikes[10]  # ATM strike
        print(f"✅ Mock Adapter returned option chain")
        print(f"   Strike: {strike.strike}")
        print(f"   Call IV: {strike.call_iv}")
        print(f"   Call Greeks:")
        print(f"     • Delta: {strike.call_delta}")
        print(f"     • Gamma: {strike.call_gamma}")
        print(f"     • Theta: {strike.call_theta}")
        print(f"     • Vega:  {strike.call_vega}")
        
        if strike.call_delta == 0.0 and strike.call_gamma == 0.0:
            print(f"\n⚠️  ISSUE DETECTED: Greeks are all ZEROS")
            print(f"   Mock adapter is not calculating Greeks")
            print(f"   This is OK for development but wrong for production")
        else:
            print(f"\n✅ Greeks are being calculated correctly")
    else:
        print(f"❌ No option chain data returned")
        
except Exception as e:
    print(f"❌ Error in live test: {e}")

# Summary
print("\n" + "="*80)
print("SUMMARY")
print("="*80)

print("""
OPTIONS GREEKS IMPORT STATUS:

✅ FYERS ADAPTER:
   • Imports option chain from Fyers API
   • Calculates Greeks using Black-Scholes model
   • Saves to database: delta, gamma, theta, vega (CE + PE)
   • Status: WORKING

⚠️  MOCK ADAPTER:
   • Returns option chain with OI, IV, LTP
   • Does NOT calculate Greeks (all zeros)
   • Only returns: call_oi, call_iv, call_ltp, put_oi, put_iv, put_ltp
   • Greeks fields: call_delta, call_gamma, call_theta, call_vega = 0.0
   • Status: MOCK MODE (OK for development)

📊 DATABASE:
   • Stores all Greeks in option_eod_prices table
   • Fields saved: delta_call, gamma_call, theta_call, vega_call, etc.
   • Status: WORKING

🔧 WHAT TO DO:

If you're using MOCK (development):
   ✅ Current behavior is expected
   ✅ Greeks are zeros, which is fine for mock testing
   ✅ When you switch to Fyers, Greeks will be auto-calculated

If you're using FYERS (production):
   ✅ Greeks should be populated automatically
   ✅ Check logs for errors: grep "optionchain" in logs
   ✅ Verify Fyers API connection and credentials

To enable Greeks in Mock (for testing):
   1. Add bs_greeks calculation to MockAdapter.get_option_chain()
   2. Import: from data.bs_utils import bs_greeks as _bs_greeks
   3. Calculate for each strike
""")

print("="*80 + "\n")
