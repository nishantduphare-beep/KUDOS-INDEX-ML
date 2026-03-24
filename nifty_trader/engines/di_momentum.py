"""
engines/di_momentum.py
Engine 2 — DI Momentum Expansion

Detects directional pressure BEFORE the ADX crossover trade triggers.
The key insight: DI lines trend before ADX confirms.

Bullish pressure:   +DI rising, -DI falling, spread widening
Bearish pressure:   -DI rising, +DI falling, spread widening
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)


@dataclass
class DIMomentumResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    primary_di_rising: bool = False
    secondary_di_falling: bool = False
    spread_widening: bool = False


class DIMomentumDetector:
    """
    Engine 2: Directional Movement expansion detection.

    Detects when DI lines are beginning to diverge — indicating
    directional pressure building up, even before a classic crossover.
    """

    def __init__(self):
        self.lookback  = config.DI_RISING_LOOKBACK             # 3
        self.spread_th = config.DI_SPREAD_WIDENING_THRESHOLD    # 2.0

    def evaluate(self, df: pd.DataFrame) -> DIMomentumResult:
        result = DIMomentumResult()

        required_len = self.lookback + 2
        if df is None or len(df) < required_len:
            result.reason = "Insufficient data"
            return result

        plus_di_series  = df["plus_di"].tail(self.lookback + 1).values
        minus_di_series = df["minus_di"].tail(self.lookback + 1).values
        adx_series      = df["adx"].tail(self.lookback + 1).values

        if len(plus_di_series) < 2:
            result.reason = "DI data unavailable"
            return result

        # Current and historical values
        plus_now   = float(plus_di_series[-1])
        minus_now  = float(minus_di_series[-1])
        adx_now    = float(adx_series[-1])

        plus_spread_now  = plus_now - minus_now
        plus_spread_prev = float(plus_di_series[-2]) - float(minus_di_series[-2])

        result.features.update({
            "plus_di": round(plus_now, 2),
            "minus_di": round(minus_now, 2),
            "adx": round(adx_now, 2),
            "di_spread": round(plus_spread_now, 2),
            "di_spread_prev": round(plus_spread_prev, 2),
        })

        # ── Determine direction ───────────────────────────────────
        if plus_now > minus_now:
            # Potential bullish → check +DI rising, -DI falling
            direction = "BULLISH"
            primary   = plus_di_series
            secondary = minus_di_series
            spread    = plus_spread_now - plus_spread_prev  # Should be positive
        else:
            # Potential bearish → check -DI rising, +DI falling
            direction = "BEARISH"
            primary   = minus_di_series
            secondary = plus_di_series
            spread    = -plus_spread_now - (-plus_spread_prev)

        # ── Condition 1: Primary DI rising ────────────────────────
        primary_rising = self._is_trending_up(primary, self.lookback)
        result.primary_di_rising = primary_rising

        # ── Condition 2: Secondary DI falling ─────────────────────
        secondary_falling = self._is_trending_down(secondary, self.lookback)
        result.secondary_di_falling = secondary_falling

        # ── Condition 3: Spread widening ──────────────────────────
        # WARNING-3 fix: absolute threshold of 2.0 DI points is too strict at high
        # DI levels (spread 30→32 is meaningful) and too loose at low levels
        # (spread 5→7 is a huge % move). Now uses dual condition: absolute OR relative.
        abs_spread_met = spread >= self.spread_th
        rel_spread_th  = abs(plus_spread_prev) * config.DI_SPREAD_PCT_THRESHOLD
        rel_spread_met = abs(spread) >= max(rel_spread_th, 0.5)  # 0.5 floor avoids noise at near-zero spread
        spread_widening = abs_spread_met or rel_spread_met
        result.spread_widening = spread_widening

        result.features["spread_change"]     = round(float(spread), 2)
        result.features["primary_rising"]    = primary_rising
        result.features["secondary_falling"] = secondary_falling
        result.features["spread_widening"]   = spread_widening
        result.features["direction"]         = direction

        # ── Aggregate ─────────────────────────────────────────────
        conditions_met = sum([primary_rising, secondary_falling, spread_widening])
        result.is_triggered = conditions_met >= 2

        if result.is_triggered:
            result.direction = direction

            # Compute slope magnitudes for strength
            primary_slope   = self._slope(primary)
            secondary_slope = -self._slope(secondary)  # Falling is positive signal
            spread_score    = min(1.0, abs(spread) / (self.spread_th * 3))

            result.strength = min(1.0,
                (primary_slope * 0.4 + secondary_slope * 0.3 + spread_score * 0.3)
            )
            result.score = round(result.strength * config.CONFIDENCE_WEIGHTS["di_momentum"], 2)
            result.reason = (
                f"DI {direction}: +DI={plus_now:.1f}, -DI={minus_now:.1f}, "
                f"spread={plus_spread_now:.1f} "
                f"(Δ{spread:+.1f}), ADX={adx_now:.1f}"
            )
        else:
            result.direction = "NEUTRAL"
            result.reason = (
                f"DI neutral: conditions={conditions_met}/3 "
                f"+DI={plus_now:.1f} -DI={minus_now:.1f} spread={plus_spread_now:.1f}"
            )

        logger.debug(f"DIMomentumDetector: {result.reason}")
        return result

    # ─── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _is_trending_up(series: np.ndarray, lookback: int) -> bool:
        """Check if series has been rising over `lookback` periods."""
        if len(series) < lookback + 1:
            return False
        tail = series[-(lookback + 1):]
        # Must have more ups than downs
        diffs = np.diff(tail)
        ups   = np.sum(diffs > 0)
        return ups >= lookback * 0.6  # At least 60% of periods rising

    @staticmethod
    def _is_trending_down(series: np.ndarray, lookback: int) -> bool:
        """Check if series has been falling over `lookback` periods."""
        if len(series) < lookback + 1:
            return False
        tail = series[-(lookback + 1):]
        diffs = np.diff(tail)
        downs = np.sum(diffs < 0)
        return downs >= lookback * 0.6

    @staticmethod
    def _slope(series: np.ndarray) -> float:
        """Normalized slope of series."""
        if len(series) < 2:
            return 0.0
        mean_val = np.mean(np.abs(series))
        if mean_val == 0:
            return 0.0
        diff = series[-1] - series[0]
        return min(1.0, abs(diff) / mean_val)
