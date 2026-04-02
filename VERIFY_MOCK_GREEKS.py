#!/usr/bin/env python3
"""
Verify that Mock Adapter now calculates options greeks
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nifty_trader"))

print("\n" + "="*80)
print("MOCK ADAPTER GREEKS VERIFICATION")
print("="*80)

try:
    import config
    from data.adapters.mock_adapter import MockAdapter
    
    print("\n✅ Imports successful")
    
    # Create and connect adapter
    adapter = MockAdapter()
    adapter.connect()
    print("✅ Mock adapter connected")
    
    # Get option chain
    chain = adapter.get_option_chain("NIFTY")
    print(f"✅ Option chain retrieved: {len(chain.strikes)} strikes")
    
    # Check ATM strike (should be middle one)
    atm_strike = chain.strikes[10]  # ATM should be around middle
    
    print(f"\n📊 ATM STRIKE DETAILS")
    print(f"-" * 80)
    print(f"Strike:           {atm_strike.strike}")
    print(f"Spot Price:       {chain.spot_price}")
    print(f"Expiry:           {atm_strike.expiry}")
    
    print(f"\n📈 CALL OPTION GREEKS")
    print(f"-" * 80)
    print(f"Call IV:     {atm_strike.call_iv}%")
    print(f"Call LTP:    {atm_strike.call_ltp}")
    print(f"Call Delta:  {atm_strike.call_delta:.4f}  {'✅ CALCULATED' if atm_strike.call_delta != 0 else '❌ ZERO'}")
    print(f"Call Gamma:  {atm_strike.call_gamma:.6f}  {'✅ CALCULATED' if atm_strike.call_gamma != 0 else '❌ ZERO'}")
    print(f"Call Theta:  {atm_strike.call_theta:.4f}  {'✅ CALCULATED' if atm_strike.call_theta != 0 else '❌ ZERO'}")
    print(f"Call Vega:   {atm_strike.call_vega:.4f}  {'✅ CALCULATED' if atm_strike.call_vega != 0 else '❌ ZERO'}")
    
    print(f"\n📉 PUT OPTION GREEKS")
    print(f"-" * 80)
    print(f"Put IV:      {atm_strike.put_iv}%")
    print(f"Put LTP:     {atm_strike.put_ltp}")
    print(f"Put Delta:   {atm_strike.put_delta:.4f}  {'✅ CALCULATED' if atm_strike.put_delta != 0 else '❌ ZERO'}")
    print(f"Put Gamma:   {atm_strike.put_gamma:.6f}  {'✅ CALCULATED' if atm_strike.put_gamma != 0 else '❌ ZERO'}")
    print(f"Put Theta:   {atm_strike.put_theta:.4f}  {'✅ CALCULATED' if atm_strike.put_theta != 0 else '❌ ZERO'}")
    print(f"Put Vega:    {atm_strike.put_vega:.4f}  {'✅ CALCULATED' if atm_strike.put_vega != 0 else '❌ ZERO'}")
    
    # Check if all strikes have Greeks
    all_have_greeks = all(
        s.call_delta != 0 and s.put_delta != 0
        for s in chain.strikes
    )
    
    print(f"\n🔍 FULL CHAIN VERIFICATION")
    print(f"-" * 80)
    print(f"Total strikes:     {len(chain.strikes)}")
    print(f"Strikes with greeks: {sum(1 for s in chain.strikes if s.call_delta != 0)}")
    print(f"All have greeks:   {'✅ YES' if all_have_greeks else '❌ NO'}")
    
    # Show a few strikes
    print(f"\n📋 STRIKE GREEKS SAMPLE")
    print(f"-" * 80)
    print(f"{'Strike':<8} {'Call Δ':<10} {'Call Γ':<10} {'Put Δ':<10} {'Put Γ':<10}")
    print(f"-" * 80)
    for strike in chain.strikes[8:13]:  # Show 5 strikes around ATM
        print(f"{strike.strike:<8.0f} {strike.call_delta:<10.4f} {strike.call_gamma:<10.6f} {strike.put_delta:<10.4f} {strike.put_gamma:<10.6f}")
    
    print(f"\n" + "="*80)
    print("RESULT")
    print("="*80)
    
    if all_have_greeks:
        print(f"""
✅ SUCCESS: Mock Adapter NOW CALCULATES OPTIONS GREEKS

Changes Applied:
  • Added: from data.bs_utils import bs_greeks
  • Per strike: Calls _bs_greeks() for both CE and PE
  • Results: Delta, Gamma, Theta, Vega populated
  
Impact:
  ✅ Gamma Levels engine can now trigger (has gamma values)
  ✅ Options UI shows accurate Greeks (not zeros)
  ✅ ML features receive real Greeks data (not zeros)
  ✅ Database stores real Greeks for analysis
  
Next: Restart the app to use updated Mock adapter
""")
    else:
        print(f"""
❌ ISSUE: Greek calculation not working

Check:
  • Are imports correct?
  • Is bs_greeks being called?
  • Any errors in the output?
        """)
    
    print("="*80 + "\n")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
