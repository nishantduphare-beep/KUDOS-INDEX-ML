"""
engines/volume_pressure.py
Engine 4 — Volume Pressure (Institutional Accumulation)

Detects large positions being built quietly:
  • Volume > 1.5× recent average
  • Small candle body with high volume (absorption / stealth accumulation)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)


@dataclass
class VolumePressureResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    volume_spike: bool = False
    stealth_accumulation: bool = False
    volume_trend_up: bool = False


class VolumePressureDetector:
    """
    Engine 4: Volume-based institutional pressure detection.

    A small-body candle on high volume typically means large players
    absorbing supply (bullish) or distribution (bearish). Combined with
    volume spikes and rising volume trend, this signals hidden intent.
    """

    def __init__(self):
        self.vol_period    = config.VOLUME_AVERAGE_PERIOD      # 20
        self.spike_mult    = config.VOLUME_SPIKE_MULTIPLIER    # 1.5
        self.small_candle  = config.SMALL_CANDLE_THRESHOLD     # 0.5 (body/range)

    def evaluate(self, df: pd.DataFrame) -> VolumePressureResult:
        result = VolumePressureResult()

        if df is None or len(df) < self.vol_period:
            result.reason = "Insufficient data"
            return result

        last = df.iloc[-1]
        last5 = df.tail(5)

        # ── Extract values ────────────────────────────────────────
        volume       = float(last.get("volume", 0))
        volume_sma   = float(last.get("volume_sma", 1))
        volume_ratio = float(last.get("volume_ratio", 1.0))
        candle_range = float(last["high"] - last["low"])
        body_size    = float(abs(last["close"] - last["open"]))
        is_bullish   = bool(last["close"] >= last["open"])

        result.features.update({
            "volume": int(volume),
            "volume_sma": round(volume_sma, 0),
            "volume_ratio": round(volume_ratio, 3),
            "candle_range": round(candle_range, 2),
            "body_size": round(body_size, 2),
            "body_ratio": round(body_size / max(candle_range, 1e-6), 4),
            "is_bullish": is_bullish,
        })

        # ── Condition 1: Volume Spike ─────────────────────────────
        volume_spike = volume_ratio >= self.spike_mult
        result.volume_spike = volume_spike

        # ── Condition 2: Stealth Accumulation ─────────────────────
        # Small body (absorption pattern) on high volume
        body_ratio = body_size / max(candle_range, 1e-6)
        stealth = volume_spike and (body_ratio < self.small_candle)
        result.stealth_accumulation = stealth
        result.features["stealth_pattern"] = stealth

        # ── Condition 3: Volume trend (last 5 candles) ────────────
        vol_ratios = last5["volume_ratio"].values if "volume_ratio" in last5 else []
        if len(vol_ratios) >= 3:
            vol_trend_up = bool(np.polyfit(range(len(vol_ratios)), vol_ratios, 1)[0] > 0)
        else:
            vol_trend_up = False
        result.volume_trend_up = vol_trend_up
        result.features["vol_5_mean_ratio"] = round(float(np.mean(vol_ratios)), 3) if len(vol_ratios) > 0 else 0

        # ── Direction inference ───────────────────────────────────
        # BUG-1 fix: 3-candle body consensus was contradicting the stealth
        # accumulation premise — if institutions are hiding intent, candle bodies
        # are deliberately ambiguous. Use close vs. candle midpoint instead:
        # close above midpoint = buying pressure absorbed into upper range (bullish)
        # close below midpoint = selling pressure absorbed into lower range (bearish)
        direction = "NEUTRAL"
        if volume_spike:
            midpoint = (float(last["high"]) + float(last["low"])) / 2.0
            close    = float(last["close"])
            if close > midpoint:
                direction = "BULLISH"
            elif close < midpoint:
                direction = "BEARISH"
            else:
                # Exact midpoint: fall back to candle open vs. close
                direction = "BULLISH" if is_bullish else "BEARISH"

        result.features["direction_inferred"] = direction

        # ── Aggregate ─────────────────────────────────────────────
        conditions_met = sum([
            result.volume_spike,
            result.stealth_accumulation,
            result.volume_trend_up,
        ])
        result.is_triggered = conditions_met >= 1 and volume_spike  # Volume spike is mandatory

        if result.is_triggered:
            result.direction = direction

            # Strength: how extreme is the volume spike
            spike_intensity = min(1.0, (volume_ratio - self.spike_mult) / 2.0 + 0.5)
            stealth_bonus   = 0.2 if stealth else 0.0
            trend_bonus     = 0.1 if vol_trend_up else 0.0
            result.strength = min(1.0, spike_intensity + stealth_bonus + trend_bonus)
            result.score    = round(result.strength * config.CONFIDENCE_WEIGHTS["volume_pressure"], 2)

            result.reason = (
                f"Volume pressure {direction}: "
                f"vol_ratio={volume_ratio:.2f}x (threshold {self.spike_mult}x), "
                f"stealth={stealth}, body_ratio={body_ratio:.2f}"
            )
        else:
            result.reason = (
                f"No volume pressure: vol_ratio={volume_ratio:.2f}x "
                f"(need >{self.spike_mult}x)"
            )

        logger.debug(f"VolumePressureDetector: {result.reason}")
        return result
