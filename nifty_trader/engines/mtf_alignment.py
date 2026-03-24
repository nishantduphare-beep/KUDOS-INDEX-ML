"""
engines/mtf_alignment.py
Multi-Timeframe Alignment Engine

Scores how well 5-min and 15-min trends agree with the 3-min signal.
Does NOT gate signals — adds a confidence modifier (+/-).

Alignment levels:
  STRONG    both 5m + 15m agree   → +MTF_SCORE_BONUS
  PARTIAL   one agrees, one neutral → +MTF_SCORE_PARTIAL_BONUS
  NEUTRAL   both neutral            → 0
  WEAK      one opposes, other neutral → -MTF_SCORE_WEAK_PENALTY
  OPPOSING  both oppose             → -MTF_SCORE_OPPOSING_PENALTY
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

import pandas as pd

import config

logger = logging.getLogger(__name__)


@dataclass
class MTFResult:
    bias_5m:     str   = "NEUTRAL"    # BULLISH / BEARISH / NEUTRAL
    bias_15m:    str   = "NEUTRAL"
    alignment:   str   = "NEUTRAL"    # STRONG / PARTIAL / NEUTRAL / WEAK / OPPOSING
    score_delta: float = 0.0          # confidence modifier to add to final score
    features:    Dict[str, Any] = field(default_factory=dict)
    reason:      str   = ""


class MTFAlignmentEngine:
    """
    Reads 5-min and 15-min DataFrames, derives directional bias from
    each, then scores how aligned they are with the 3-min signal direction.
    """

    def evaluate(
        self,
        df_5m:    Optional[pd.DataFrame],
        df_15m:   Optional[pd.DataFrame],
        direction: str,                     # consensus direction from 3-min engines
    ) -> MTFResult:
        result = MTFResult()

        bias_5m  = self._get_bias(df_5m)
        bias_15m = self._get_bias(df_15m)

        result.bias_5m  = bias_5m
        result.bias_15m = bias_15m

        agrees_5m   = (bias_5m  == direction)
        opposes_5m  = (bias_5m  != "NEUTRAL" and bias_5m  != direction)
        agrees_15m  = (bias_15m == direction)
        opposes_15m = (bias_15m != "NEUTRAL" and bias_15m != direction)

        agrees  = int(agrees_5m)  + int(agrees_15m)
        opposes = int(opposes_5m) + int(opposes_15m)

        if agrees == 2 and opposes == 0:
            result.alignment   = "STRONG"
            result.score_delta = +config.MTF_SCORE_BONUS
        elif agrees == 1 and opposes == 0:
            result.alignment   = "PARTIAL"
            result.score_delta = +config.MTF_SCORE_PARTIAL_BONUS
        elif agrees == 0 and opposes == 0:
            result.alignment   = "NEUTRAL"
            result.score_delta = 0.0
        elif opposes == 1 and agrees == 0:
            result.alignment   = "WEAK"
            result.score_delta = -config.MTF_SCORE_WEAK_PENALTY
        else:
            result.alignment   = "OPPOSING"
            result.score_delta = -config.MTF_SCORE_OPPOSING_PENALTY

        result.features = {
            "bias_5m":     bias_5m,
            "bias_15m":    bias_15m,
            "alignment":   result.alignment,
            "score_delta": result.score_delta,
        }
        result.reason = (
            f"MTF: 5m={bias_5m}  15m={bias_15m}  →  "
            f"{result.alignment}  ({result.score_delta:+.0f}%)"
        )
        logger.debug(f"MTFAlignmentEngine: {result.reason}")
        return result

    @staticmethod
    def _get_bias(df: Optional[pd.DataFrame]) -> str:
        """Derive directional bias from a single timeframe DataFrame."""
        if df is None or len(df) < 3:
            return "NEUTRAL"
        last     = df.iloc[-1]
        plus_di  = float(last.get("plus_di",  0))
        minus_di = float(last.get("minus_di", 0))
        adx      = float(last.get("adx",      0))

        # Only call a direction if ADX is strong enough
        if adx < config.MTF_MIN_ADX:
            return "NEUTRAL"
        if plus_di > minus_di + 3:
            return "BULLISH"
        if minus_di > plus_di + 3:
            return "BEARISH"
        return "NEUTRAL"
