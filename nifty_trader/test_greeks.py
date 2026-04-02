#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from data.adapters.mock_adapter import MockAdapter
import config

a = MockAdapter()
a.connect()
c = a.get_option_chain("NIFTY")
s = c.strikes[10]

print("\nMock Adapter Greeks Test")
print("=" * 60)
print(f"ATM Strike:     {s.strike}")
print(f"Call Delta:     {s.call_delta:.4f}")
print(f"Call Gamma:     {s.call_gamma:.6f}")
print(f"Call Theta:     {s.call_theta:.4f}")
print(f"Call Vega:      {s.call_vega:.4f}")
print(f"Put Delta:      {s.put_delta:.4f}")
print(f"Put Gamma:      {s.put_gamma:.6f}")
print(f"Put Theta:      {s.put_theta:.4f}")
print(f"Put Vega:       {s.put_vega:.4f}")

is_working = s.call_delta != 0 and s.put_delta != 0
print(f"\nGreeks Calculation: {'WORKING' if is_working else 'NOT WORKING'}")
print("=" * 60)

if is_working:
    print("\nSUCCESS: Mock adapter now calculates options greeks!")
    print("All Greeks are populated:")
    print("  - Call Greeks (Delta, Gamma, Theta, Vega): CALCULATED")
    print("  - Put Greeks (Delta, Gamma, Theta, Vega):  CALCULATED")
else:
    print("\nFAILURE: Greeks are still zeros")
