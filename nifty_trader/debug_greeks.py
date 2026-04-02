#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from data.adapters.mock_adapter import MockAdapter
import config

a = MockAdapter()
a.connect()
c = a.get_option_chain("NIFTY")

print("\nMock Adapter Greeks - Full Chain Test")
print("=" * 80)
print(f"Spot Price: {c.spot_price}")
print("=" * 80)
print(f"{'Strike':<10} {'Call D':<10} {'Call G':<12} {'Put D':<10} {'Put G':<12}")
print("=" * 80)

for i, strike in enumerate(c.strikes):
    marker = " <- ATM" if i == 10 else ""
    print(f"{strike.strike:<10.0f} {strike.call_delta:<10.4f} {strike.call_gamma:<12.6f} {strike.put_delta:<10.4f} {strike.put_gamma:<12.6f}{marker}")

# Special check - test the calculation directly
print("\n" + "=" * 80)
print("Direct Black-Scholes Test")
print("=" * 80)

from data.bs_utils import bs_greeks

spot = c.spot_price
strike = c.strikes[10].strike
tte = 1.0 / 52.0
rate = 0.065

# Test with Call
print(f"\nTest Call Greeks (Spot={spot}, Strike={strike}, TTE={tte:.4f})")
call_iv = c.strikes[10].call_iv / 100.0
print(f"IV: {call_iv:.4f}")

try:
    cg = bs_greeks(spot, strike, tte, rate, "CE", call_iv)
    print(f"Result: {cg}")
except Exception as e:
    print(f"Error: {e}")

# Test with Put
print(f"\nTest Put Greeks (Spot={spot}, Strike={strike}, TTE={tte:.4f})")
put_iv = c.strikes[10].put_iv / 100.0
print(f"IV: {put_iv:.4f}")

try:
    pg = bs_greeks(spot, strike, tte, rate, "PE", put_iv)
    print(f"Result: {pg}")
except Exception as e:
    print(f"Error: {e}")
