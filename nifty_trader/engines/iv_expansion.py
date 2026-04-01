"""
engines/iv_expansion.py
Engine 7 — Implied Volatility Expansion Detection

When market participants expect a significant move, they bid up option
premiums → IV rises. Detecting a sharp IV expansion gives early warning
of an impending breakout before the price move starts.

IV Skew (directional bias):
  Put IV > Call IV by significant margin → bearish fear premium
    → market expecting downside → BEARISH signal
  Call IV > Put IV by significant margin → bullish call buying
    → market expecting upside → BULLISH signal
  Balanced IV → non-directional expansion (combined with other engines)

IV Change (expansion):
  ATM IV rising vs prior reading → options being bought (expected move)
  Threshold: 10% rise in average ATM IV triggers engine
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any
import numpy as np

import config
from data.structures import OptionChain
from data.bs_utils import bs_iv as _bs_iv

logger = logging.getLogger(__name__)

_RISK_FREE_RATE = config.RISK_FREE_RATE  # defined in config.py


def compute_iv(option_ltp: float, spot: float, strike: float,
               expiry_str: str, is_call: bool,
               r: float = _RISK_FREE_RATE) -> float:
    """
    Implied volatility from option LTP.
    Delegates to bs_utils.bs_iv (Brent root-finding, canonical solver).
    Returns IV as a percentage (e.g. 15.5 for 15.5%), or 0.0 if unsolvable.

    expiry_str formats accepted: "27MAR2025", "2025-03-27", "27-Mar-2025".
    """
    if option_ltp <= 0 or spot <= 0 or strike <= 0:
        return 0.0

    # Parse expiry to get time-to-expiry in years
    T = 0.0
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y", "%d%b%y"):
        try:
            exp_date = datetime.strptime(expiry_str.strip().upper(), fmt.upper()).date()
            days_left = max(1, (exp_date - date.today()).days)
            T = days_left / 365.0
            break
        except ValueError:
            continue
    if T <= 0:
        T = 7.0 / 365.0  # fallback: 1 week

    opt_type = "CE" if is_call else "PE"
    return _bs_iv(option_ltp, spot, strike, T, r, opt_type)


@dataclass
class IVExpansionResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    iv_expanding: bool = False      # ATM IV rising vs prev
    iv_skew_bearish: bool = False   # Put IV >> Call IV → fear
    iv_skew_bullish: bool = False   # Call IV >> Put IV → speculation
    high_absolute_iv: bool = False  # IV is high in absolute terms


class IVExpansionDetector:
    """
    Engine 7: Implied volatility expansion and skew detection.

    Options market is often smarter than price action — rising IV on
    ATM options signals that institutional players are loading up on
    directional bets before a major move.
    """

    def __init__(self):
        self.expansion_th = config.IV_EXPANSION_THRESHOLD   # 0.10 (10%)
        self.skew_th      = config.IV_SKEW_THRESHOLD        # 1.15

    def evaluate(
        self,
        chain: OptionChain,
        prev_chain: Optional[OptionChain] = None
    ) -> IVExpansionResult:
        result = IVExpansionResult()

        if chain is None or not chain.strikes:
            result.reason = "No option chain data"
            return result

        # ── Get ATM strikes for IV analysis ───────────────────────
        atm_strikes = chain.get_atm_strikes(n=5)
        if not atm_strikes:
            result.reason = "No ATM strikes available"
            return result

        call_ivs = [s.call_iv for s in atm_strikes if s.call_iv > 0]
        put_ivs  = [s.put_iv  for s in atm_strikes if s.put_iv  > 0]

        # IV=0 fix: brokers like Fyers don't return IV in their option chain.
        # When IV values are missing, compute them via Black-Scholes from LTP.
        if not call_ivs and not put_ivs:
            spot   = chain.spot_price
            expiry = atm_strikes[0].expiry if atm_strikes else ""
            for s in atm_strikes:
                if s.call_ltp > 0:
                    iv = compute_iv(s.call_ltp, spot, s.strike, expiry, is_call=True)
                    if iv > 0:
                        call_ivs.append(iv)
                if s.put_ltp > 0:
                    iv = compute_iv(s.put_ltp, spot, s.strike, expiry, is_call=False)
                    if iv > 0:
                        put_ivs.append(iv)
            if call_ivs or put_ivs:
                result.features["iv_source"] = "computed_bs"
                logger.debug(f"IVExpansionDetector: IV computed via Black-Scholes "
                             f"({len(call_ivs)} calls, {len(put_ivs)} puts)")
            else:
                result.reason = "No IV data and no LTP available for BS computation"
                return result
        else:
            result.features["iv_source"] = "broker"

        avg_call_iv = float(np.mean(call_ivs)) if call_ivs else 0.0
        avg_put_iv  = float(np.mean(put_ivs))  if put_ivs  else 0.0
        avg_atm_iv  = (avg_call_iv + avg_put_iv) / 2.0 if (call_ivs and put_ivs) else max(avg_call_iv, avg_put_iv)

        result.features.update({
            "avg_call_iv":  round(avg_call_iv, 2),
            "avg_put_iv":   round(avg_put_iv, 2),
            "avg_atm_iv":   round(avg_atm_iv, 2),
            "atm_strikes_count": len(atm_strikes),
        })

        # ── Condition 1: IV Expansion (vs prev chain) ─────────────
        iv_change_pct = 0.0
        if prev_chain is not None:
            prev_atm = prev_chain.get_atm_strikes(n=5)
            if prev_atm:
                prev_call_ivs = [s.call_iv for s in prev_atm if s.call_iv > 0]
                prev_put_ivs  = [s.put_iv  for s in prev_atm if s.put_iv  > 0]
                prev_avg_iv   = 0.0
                if prev_call_ivs or prev_put_ivs:
                    all_prev = prev_call_ivs + prev_put_ivs
                    prev_avg_iv = float(np.mean(all_prev))
                if prev_avg_iv > 0:
                    iv_change_pct = (avg_atm_iv - prev_avg_iv) / prev_avg_iv
                    result.features["iv_change_pct"] = round(iv_change_pct, 4)
                    result.features["prev_avg_iv"]   = round(prev_avg_iv, 2)
                    result.iv_expanding = iv_change_pct >= self.expansion_th

        # ── Condition 2: IV Skew ───────────────────────────────────
        if avg_call_iv > 0 and avg_put_iv > 0:
            skew_ratio = avg_put_iv / avg_call_iv
            result.features["iv_skew_ratio"] = round(skew_ratio, 3)

            result.iv_skew_bearish = skew_ratio >= self.skew_th        # Put IV dominant
            result.iv_skew_bullish = skew_ratio <= (1.0 / self.skew_th) # Call IV dominant
        else:
            skew_ratio = 1.0
            result.features["iv_skew_ratio"] = 1.0

        # ── Condition 3: High absolute IV level ───────────────────
        # Heuristic: ATM IV > 15% for indices = elevated (typical range 10-30%)
        result.high_absolute_iv = avg_atm_iv > 15.0
        result.features["high_absolute_iv"] = result.high_absolute_iv

        # ── Determine direction ────────────────────────────────────
        direction = "NEUTRAL"
        if result.iv_skew_bearish:
            direction = "BEARISH"
        elif result.iv_skew_bullish:
            direction = "BULLISH"

        # ── Aggregate ─────────────────────────────────────────────
        conditions_met = sum([
            result.iv_expanding,
            result.iv_skew_bearish or result.iv_skew_bullish,
            result.high_absolute_iv,
        ])

        # Must have at least expansion OR skew to trigger
        if (result.iv_expanding or (result.iv_skew_bearish or result.iv_skew_bullish)) and avg_atm_iv > 0:
            result.is_triggered = True
            result.direction    = direction

            expansion_component = min(1.0, iv_change_pct / (self.expansion_th * 2)) if result.iv_expanding else 0.3
            skew_component = min(1.0, abs(skew_ratio - 1.0) / 0.3) if (result.iv_skew_bearish or result.iv_skew_bullish) else 0.0
            level_component = 0.2 if result.high_absolute_iv else 0.0
            result.strength = min(1.0, 0.4 + expansion_component * 0.35 + skew_component * 0.15 + level_component)

        if result.is_triggered:
            result.score = round(
                result.strength * config.CONFIDENCE_WEIGHTS["iv_expansion"], 2
            )
            result.reason = (
                f"IV expansion {direction}: "
                f"avg_iv={avg_atm_iv:.1f}%, iv_change={iv_change_pct:+.1%}, "
                f"skew={result.features.get('iv_skew_ratio', 1.0):.2f} "
                f"(bull={result.iv_skew_bullish}, bear={result.iv_skew_bearish})"
            )
        else:
            result.reason = (
                f"No IV signal: avg_iv={avg_atm_iv:.1f}%, "
                f"expanding={result.iv_expanding}, "
                f"skew={result.features.get('iv_skew_ratio', 1.0):.2f}"
            )

        logger.debug(f"IVExpansionDetector: {result.reason}")
        return result
