"""
data/bs_utils.py
──────────────────────────────────────────────────────────────────
Shared Black-Scholes utility functions — broker-agnostic.

Used by:
  • data/adapters/fyers_adapter.py  — option chain IV + Greeks
  • data/eod_auditor.py             — daily data repair / recompute

Keeping these in one place ensures IV and Greeks are always computed
with the same formula regardless of which broker adapter is active.
"""

import math


def bs_iv(ltp: float, spot: float, strike: float,
          tte: float, rate: float, opt_type: str) -> float:
    """
    Compute implied volatility via Black-Scholes + Brent root-finding.
    Returns IV as a percentage (e.g. 18.5 means 18.5%).
    Returns 0.0 when IV cannot be determined.

    ltp      — option market price
    spot     — underlying spot price
    strike   — option strike
    tte      — time to expiry in years (e.g. 0.0274 for 10 days)
    rate     — risk-free rate (e.g. 0.065 for 6.5%)
    opt_type — "CE" or "PE"
    """
    if ltp <= 0 or spot <= 0 or strike <= 0 or tte <= 0:
        return 0.0
    try:
        from scipy.stats import norm
        from scipy.optimize import brentq

        def bs(sigma: float) -> float:
            if sigma <= 1e-6:
                return 0.0
            d1 = (math.log(spot / strike) + (rate + 0.5 * sigma ** 2) * tte) / (sigma * math.sqrt(tte))
            d2 = d1 - sigma * math.sqrt(tte)
            if opt_type == "CE":
                return spot * norm.cdf(d1) - strike * math.exp(-rate * tte) * norm.cdf(d2)
            else:
                return strike * math.exp(-rate * tte) * norm.cdf(-d2) - spot * norm.cdf(-d1)

        # Intrinsic value check — LTP below intrinsic means bad data, skip
        intrinsic = (max(0.0, spot - strike) if opt_type == "CE"
                     else max(0.0, strike - spot))
        if ltp < intrinsic * 0.99:
            return 0.0

        iv = brentq(lambda s: bs(s) - ltp, 1e-4, 20.0, maxiter=100, xtol=1e-4)
        return round(iv * 100.0, 2)   # express as percentage
    except Exception:
        return 0.0


def bs_greeks(spot: float, strike: float, tte: float, rate: float,
              opt_type: str, iv_pct: float) -> dict:
    """
    Compute Black-Scholes Greeks from already-computed IV (expressed as %).
    Returns dict with delta, gamma, theta (per calendar day), vega (per 1% IV).

    Sign conventions (standard):
      delta — call: 0→+1 ;  put: −1→0
      gamma — always ≥ 0
      theta — always ≤ 0  (time decay costs money)
      vega  — always ≥ 0  (per 1% rise in IV)
    """
    _zero = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    if iv_pct <= 0 or spot <= 0 or strike <= 0 or tte <= 0:
        return _zero
    try:
        from scipy.stats import norm
        sigma    = iv_pct / 100.0
        sqrt_tte = math.sqrt(tte)
        d1 = (math.log(spot / strike) + (rate + 0.5 * sigma ** 2) * tte) / (sigma * sqrt_tte)
        d2 = d1 - sigma * sqrt_tte
        nd1 = norm.pdf(d1)

        delta = norm.cdf(d1) if opt_type == "CE" else norm.cdf(d1) - 1.0
        gamma = nd1 / (spot * sigma * sqrt_tte)
        theta = (
            -(spot * nd1 * sigma) / (2.0 * sqrt_tte)
            - rate * strike * math.exp(-rate * tte) * (
                norm.cdf(d2) if opt_type == "CE" else norm.cdf(-d2)
            )
        ) / 365.0
        vega = spot * nd1 * sqrt_tte / 100.0   # per 1% change in IV

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega":  round(vega,  4),
        }
    except Exception:
        return _zero
