"""
engines/compression.py
Engine 1 — Compression Detector

Detects when price is coiling before an expansion move.

Criteria:
  • Last 5 candles range < 70% of 20-candle average range
  • ATR declining for last 3 periods
  • Volatility contraction confirmed
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"           # NEUTRAL (compression has no direction)
    strength: float = 0.0                # 0.0 → 1.0
    score: float = 0.0                   # Weighted points (0-25)
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    range_compressed: bool = False
    atr_declining: bool = False
    volatility_contracted: bool = False


class CompressionDetector:
    """
    Engine 1: Detects energy build-up through price compression.

    A compression phase means the market is coiling, accumulating energy
    for a directional move. Three sub-conditions must hold.
    """

    def __init__(self):
        self.lookback  = config.COMPRESSION_CANDLE_LOOKBACK   # 5
        self.ratio     = config.COMPRESSION_RANGE_RATIO        # 0.70
        self.atr_lb    = config.ATR_DECLINING_LOOKBACK          # 3

    def evaluate(self, df: pd.DataFrame) -> CompressionResult:
        """
        Evaluate compression on the latest candles.

        Args:
            df: DataFrame with OHLCV + indicators (from DataManager)

        Returns:
            CompressionResult
        """
        result = CompressionResult()

        if df is None or len(df) < max(20, self.lookback + 1):
            result.reason = "Insufficient data"
            return result

        # ── Condition 1: Range Compression ───────────────────────
        # Last N candles range < 70% of rolling 20-candle average
        recent_ranges = (df["high"] - df["low"]).tail(self.lookback)
        avg_range     = (df["high"] - df["low"]).rolling(20).mean().iloc[-1]

        if avg_range > 0:
            recent_avg_range = recent_ranges.mean()
            range_ratio = recent_avg_range / avg_range
            result.range_compressed = range_ratio < self.ratio
            result.features["recent_avg_range"]  = round(float(recent_avg_range), 4)
            result.features["avg_20_range"]       = round(float(avg_range), 4)
            result.features["range_ratio"]        = round(float(range_ratio), 4)
            result.features["range_threshold"]    = self.ratio
        else:
            range_ratio = 1.0

        # ── Condition 2: ATR Declining ────────────────────────────
        atr_series = df["atr"].dropna().tail(self.atr_lb + 1)
        if len(atr_series) >= self.atr_lb + 1:
            atr_values = atr_series.values
            # ATR is declining if each value < previous
            atr_declining = all(
                atr_values[i] < atr_values[i - 1]
                for i in range(1, len(atr_values))
            )
            atr_slope = (atr_values[-1] - atr_values[0]) / max(atr_values[0], 1)
            result.atr_declining = atr_declining
            result.features["atr_current"] = round(float(atr_values[-1]), 4)
            result.features["atr_slope"]   = round(float(atr_slope), 6)
        else:
            atr_declining = False

        # ── Condition 3: Volatility Contraction ───────────────────
        # Defined as: std of close prices in recent window < std in prior window
        if len(df) >= self.lookback * 2:
            vol_recent = df["close"].tail(self.lookback).std()
            vol_prior  = df["close"].iloc[-(self.lookback*2):-self.lookback].std()
            vol_contracted = vol_recent < vol_prior * 0.85
            result.volatility_contracted = vol_contracted
            result.features["vol_recent"]      = round(float(vol_recent), 4)
            result.features["vol_prior"]       = round(float(vol_prior), 4)
            result.features["vol_ratio"]       = round(float(vol_recent / max(vol_prior, 1e-6)), 4)
        else:
            vol_contracted = False

        # ── Aggregate ─────────────────────────────────────────────
        conditions_met = sum([
            result.range_compressed,
            result.atr_declining,
            result.volatility_contracted,
        ])
        result.is_triggered = conditions_met >= 2  # Need at least 2 of 3

        if result.is_triggered:
            # Strength = proportion of conditions met + how compressed
            compression_depth = max(0, 1 - (range_ratio / self.ratio))
            result.strength = min(1.0, (conditions_met / 3.0) * 0.7 + compression_depth * 0.3)
            result.score    = round(result.strength * config.CONFIDENCE_WEIGHTS["compression"], 2)
            result.reason = (
                f"Compression active: "
                f"range_ratio={result.features.get('range_ratio', 0):.2f} "
                f"(threshold {self.ratio}), "
                f"ATR_declining={result.atr_declining}, "
                f"vol_contracted={result.volatility_contracted}"
            )
        else:
            result.reason = (
                f"No compression: conditions_met={conditions_met}/3 "
                f"(range={result.range_compressed}, "
                f"atr={result.atr_declining}, "
                f"vol={result.volatility_contracted})"
            )

        logger.debug(f"CompressionDetector: {result.reason}")
        return result

