"""
engines/liquidity_trap.py
Engine 5 — Liquidity Sweep / Trap Detection

Detects institutional stop-hunts: a candle wicks through a prior
swing high/low (sweeping resting stop orders), then closes back inside
the range — a classic liquidity trap / false breakout.

Bullish trap (buy signal):
  Price sweeps BELOW prior swing low (triggers short stops),
  then closes back ABOVE that low → trapped shorts, price reverses UP.

Bearish trap (sell signal):
  Price sweeps ABOVE prior swing high (triggers long stops),
  then closes back BELOW that high → trapped longs, price reverses DOWN.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)


@dataclass
class LiquidityTrapResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    sweep_up: bool = False       # Swept prior swing HIGH (bearish trap)
    sweep_down: bool = False     # Swept prior swing LOW  (bullish trap)
    reversal_confirmed: bool = False  # Body closes back inside range


class LiquidityTrapDetector:
    """
    Engine 5: Liquidity sweep and trap detection.

    Institutional players routinely sweep obvious liquidity pools
    (clusters of stop orders) before reversing. Detecting this gives
    an early entry signal in the TRUE direction of the move.
    """

    def __init__(self):
        self.lookback    = config.LIQUIDITY_SWEEP_LOOKBACK   # 10
        self.wick_ratio  = config.LIQUIDITY_WICK_RATIO       # 0.5

    def evaluate(self, df: pd.DataFrame) -> LiquidityTrapResult:
        result = LiquidityTrapResult()

        required = self.lookback + 2
        if df is None or len(df) < required:
            result.reason = "Insufficient data"
            return result

        # Last candle vs prior swing range (excluding last candle)
        last        = df.iloc[-1]
        prior       = df.iloc[-(self.lookback + 1):-1]

        swing_high  = float(prior["high"].max())
        swing_low   = float(prior["low"].min())
        candle_high = float(last["high"])
        candle_low  = float(last["low"])
        candle_open = float(last["open"])
        candle_close= float(last["close"])
        candle_range= candle_high - candle_low

        result.features.update({
            "swing_high":  round(swing_high, 2),
            "swing_low":   round(swing_low, 2),
            "candle_high": round(candle_high, 2),
            "candle_low":  round(candle_low, 2),
            "candle_range":round(candle_range, 2),
        })

        if candle_range < 1e-6:
            result.reason = "Zero range candle"
            return result

        # ── Bearish Trap: sweep above prior swing HIGH ─────────────
        swept_above = candle_high > swing_high
        if swept_above:
            # Wick above the swing high
            upper_wick     = candle_high - max(candle_open, candle_close)
            sweep_size     = candle_high - swing_high
            wick_ok        = upper_wick / candle_range >= self.wick_ratio
            closed_below   = candle_close < swing_high    # Closed back inside

            result.features.update({
                "upper_wick":   round(upper_wick, 2),
                "sweep_size_up":round(sweep_size, 2),
                "wick_ratio_up":round(upper_wick / candle_range, 4),
            })

            if wick_ok and closed_below:
                result.sweep_up = True
                result.reversal_confirmed = True

        # ── Bullish Trap: sweep below prior swing LOW ──────────────
        swept_below = candle_low < swing_low
        if swept_below:
            lower_wick     = min(candle_open, candle_close) - candle_low
            sweep_size     = swing_low - candle_low
            wick_ok        = lower_wick / candle_range >= self.wick_ratio
            closed_above   = candle_close > swing_low     # Closed back inside

            result.features.update({
                "lower_wick":    round(lower_wick, 2),
                "sweep_size_dn": round(sweep_size, 2),
                "wick_ratio_dn": round(lower_wick / candle_range, 4),
            })

            if wick_ok and closed_above:
                result.sweep_down = True
                result.reversal_confirmed = True

        # ── Volume confirmation ────────────────────────────────────
        volume_ratio = float(last.get("volume_ratio", 1.0))
        high_volume  = volume_ratio >= 1.2
        result.features["volume_ratio"] = round(volume_ratio, 3)
        result.features["high_volume"]  = high_volume

        # ── Aggregate ─────────────────────────────────────────────
        # Prefer the larger sweep if both happened (rare)
        if result.sweep_down and result.sweep_up:
            # Take whichever wick is larger
            up_size = result.features.get("sweep_size_up", 0)
            dn_size = result.features.get("sweep_size_dn", 0)
            result.sweep_up   = up_size >= dn_size
            result.sweep_down = dn_size >  up_size

        if result.sweep_up and result.reversal_confirmed:
            result.is_triggered = True
            result.direction    = "BEARISH"
            sweep_depth = result.features.get("sweep_size_up", 0) / max(candle_range, 1e-6)
            result.strength = min(1.0,
                0.5 + sweep_depth * 0.3 + (0.2 if high_volume else 0.0)
            )

        elif result.sweep_down and result.reversal_confirmed:
            result.is_triggered = True
            result.direction    = "BULLISH"
            sweep_depth = result.features.get("sweep_size_dn", 0) / max(candle_range, 1e-6)
            result.strength = min(1.0,
                0.5 + sweep_depth * 0.3 + (0.2 if high_volume else 0.0)
            )

        if result.is_triggered:
            result.score = round(
                result.strength * config.CONFIDENCE_WEIGHTS["liquidity_trap"], 2
            )
            result.reason = (
                f"Liquidity trap {result.direction}: "
                f"sweep_{'up' if result.sweep_up else 'down'}=True, "
                f"reversal_confirmed={result.reversal_confirmed}, "
                f"vol_ratio={volume_ratio:.2f}"
            )
        else:
            result.reason = (
                f"No liquidity trap: "
                f"swept_above={swept_above}, swept_below={swept_below}, "
                f"reversal={result.reversal_confirmed}"
            )

        logger.debug(f"LiquidityTrapDetector: {result.reason}")
        return result
