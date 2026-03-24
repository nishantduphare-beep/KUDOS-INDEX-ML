"""
engines/market_regime.py
Engine 8 — Market Regime Detection

Classifies the current market regime using Choppiness Index + ADX + ATR:

  TRENDING   — ADX > 25 AND CHOP < 61.8, clear directional move underway
  RANGING    — CHOP > 61.8, price oscillating in a band
  VOLATILE   — ATR spike (current ATR > 1.5× recent average)

Ranging detection uses the Choppiness Index (CHOP) instead of ADX < 20
because ADX has 3 layers of Wilder smoothing (ATR → DX → ADX), causing
5-10 candle lag on regime transitions. CHOP responds within 1-2 candles.

CHOP formula: 100 × log10(Σ TR(1,n) / (HH_n − LL_n)) / log10(n)
  > 61.8 = ranging/choppy
  < 38.2 = strongly trending
  38.2–61.8 = transitional / mixed

Why this matters:
  In TRENDING regimes → DI, Compression, Volume signals are highly reliable
  In RANGING regimes  → Engine 8 abstains from directional vote (mean-reversion
                        contradicts the breakout framework); SignalAggregator
                        blocks Trade Signal escalation entirely.
  In VOLATILE regimes → Liquidity traps and IV signals are most useful

Signal direction:
  TRENDING  → direction of the dominant DI (+DI vs -DI)
  RANGING   → NEUTRAL / abstain (no directional vote — avoids contradiction)
  VOLATILE  → price momentum direction (close vs open over last 3 candles)
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)

REGIME_TRENDING  = "TRENDING"
REGIME_RANGING   = "RANGING"
REGIME_VOLATILE  = "VOLATILE"


@dataclass
class MarketRegimeResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    regime: str = "UNKNOWN"          # TRENDING | RANGING | VOLATILE
    trending: bool = False
    ranging: bool = False
    volatile: bool = False


class MarketRegimeDetector:
    """
    Engine 8: Market regime classification and directional bias.

    Identifies the structural context in which signals are being generated.
    TRENDING regime adds conviction to the combined signal.
    RANGING regime: engine abstains (is_triggered=False) — avoids issuing
    a mean-reversion direction inside a breakout-based aggregator, which
    was identified as a critical directional contradiction.
    """

    def __init__(self):
        self.adx_trending  = config.REGIME_ADX_TRENDING      # 25.0
        self.atr_vol_mult  = config.REGIME_ATR_VOLATILE_MULT # 1.5
        self.chop_period   = config.CHOP_PERIOD              # 14
        self.chop_ranging  = config.CHOP_RANGING_THRESHOLD   # 61.8
        self.chop_trending = config.CHOP_TRENDING_THRESHOLD  # 38.2

    @staticmethod
    def _compute_chop(df: pd.DataFrame, period: int) -> float:
        """
        Choppiness Index: 100 × log10(Σ TR(1,n) / (HH_n − LL_n)) / log10(n)
        > 61.8 → ranging/choppy; < 38.2 → strongly trending.
        Responds within 1-2 candles vs. ADX lag of 5-10 candles.
        """
        if len(df) < period + 1:
            return 50.0  # neutral / insufficient data
        tail = df.tail(period + 1)
        prev_close = tail["close"].shift(1)
        tr = pd.concat([
            tail["high"] - tail["low"],
            (tail["high"] - prev_close).abs(),
            (tail["low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        tr_sum  = float(tr.iloc[1:].sum())
        hh      = float(tail["high"].iloc[1:].max())
        ll      = float(tail["low"].iloc[1:].min())
        hl_rng  = hh - ll
        if hl_rng <= 0 or tr_sum <= 0:
            return 50.0
        chop = 100.0 * math.log10(tr_sum / hl_rng) / math.log10(period)
        return round(min(100.0, max(0.0, chop)), 2)

    @staticmethod
    def _compute_er(df: pd.DataFrame, period: int = 10) -> float:
        """
        Efficiency Ratio (Perry Kaufman): |close_n - close_0| / Σ|close_i - close_{i-1}|
        0 = choppy/ranging; 1 = strongly trending. Used as secondary confirmation.
        """
        if len(df) < period + 1:
            return 0.5
        closes = df["close"].tail(period + 1).values
        direction = abs(float(closes[-1]) - float(closes[0]))
        volatility = sum(abs(float(closes[i]) - float(closes[i - 1])) for i in range(1, len(closes)))
        if volatility == 0:
            return 0.0
        return round(min(1.0, direction / volatility), 4)

    def evaluate(self, df: pd.DataFrame) -> MarketRegimeResult:
        result = MarketRegimeResult()

        required = max(config.ADX_PERIOD, config.ATR_PERIOD, self.chop_period) + 5
        if df is None or len(df) < required:
            result.reason = "Insufficient data"
            return result

        last = df.iloc[-1]

        # ── Extract indicators ────────────────────────────────────
        adx      = float(last.get("adx", 0))
        plus_di  = float(last.get("plus_di", 0))
        minus_di = float(last.get("minus_di", 0))
        atr_now  = float(last.get("atr", 0))

        # ATR baseline: rolling average of ATR over last 20 periods
        atr_series = df["atr"].dropna().tail(20)
        atr_avg    = float(atr_series.mean()) if len(atr_series) > 0 else atr_now
        atr_ratio  = atr_now / max(atr_avg, 1e-6)

        # Choppiness Index and Efficiency Ratio
        chop = self._compute_chop(df, self.chop_period)
        er   = self._compute_er(df, self.chop_period)

        result.features.update({
            "adx":       round(adx, 2),
            "plus_di":   round(plus_di, 2),
            "minus_di":  round(minus_di, 2),
            "atr_now":   round(atr_now, 4),
            "atr_avg":   round(atr_avg, 4),
            "atr_ratio": round(atr_ratio, 3),
            "chop":      chop,
            "er":        er,
        })

        # ── Classify regime ───────────────────────────────────────
        # Priority: VOLATILE > TRENDING > RANGING > AMBIGUOUS
        volatile = atr_ratio >= self.atr_vol_mult
        # TRENDING: strong ADX AND CHOP not in ranging zone
        trending = (adx >= self.adx_trending) and (chop < self.chop_ranging) and not volatile
        # RANGING: CHOP > threshold (fast signal, 1-2 candle response)
        ranging  = (chop >= self.chop_ranging) and not volatile

        result.volatile = volatile
        result.trending = trending
        result.ranging  = ranging

        # ── Determine direction ────────────────────────────────────
        direction = "NEUTRAL"

        if trending:
            result.regime = REGIME_TRENDING
            direction = "BULLISH" if plus_di > minus_di else "BEARISH"
            result.features["trend_strength"] = round((adx - self.adx_trending) / self.adx_trending, 3)

        elif volatile:
            result.regime = REGIME_VOLATILE
            # Direction: use DI (consistent with TRENDING; avoids the weak
            # 3-candle body inference identified in volume pressure audit).
            # Net move stored as supplementary feature only.
            recent   = df.tail(3)
            net_move = float(recent["close"].iloc[-1] - recent["close"].iloc[0])
            result.features["net_move_3c"] = round(net_move, 2)
            if plus_di > minus_di:
                direction = "BULLISH"
            elif minus_di > plus_di:
                direction = "BEARISH"
            else:
                direction = "BULLISH" if net_move >= 0 else "BEARISH"

        elif ranging:
            result.regime = REGIME_RANGING
            # CRITICAL FIX: Previously gave mean-reversion direction (contradicts
            # breakout framework). Now abstains — SignalAggregator blocks Trade
            # Signal escalation when ranging; engine does not pollute directional vote.
            direction = "NEUTRAL"

        # ── Aggregate ─────────────────────────────────────────────
        # RANGING: is_triggered = False (abstain — no directional contribution)
        # TRENDING / VOLATILE: trigger when direction is clear
        if trending or volatile:
            result.is_triggered = direction != "NEUTRAL"
        else:
            result.is_triggered = False  # ranging or ambiguous → abstain

        if result.is_triggered:
            result.direction = direction

            if trending:
                adx_excess    = (adx - self.adx_trending) / self.adx_trending
                di_divergence = abs(plus_di - minus_di) / max(plus_di + minus_di, 1)
                # Bonus for low CHOP (confirms clean trend)
                chop_bonus    = max(0.0, (self.chop_ranging - chop) / self.chop_ranging) * 0.2
                result.strength = min(1.0, 0.4 + adx_excess * 0.25 + di_divergence * 0.25 + chop_bonus)
            elif volatile:
                result.strength = min(1.0, 0.5 + (atr_ratio - self.atr_vol_mult) * 0.2)

            result.score = round(
                result.strength * config.CONFIDENCE_WEIGHTS["market_regime"], 2
            )
            result.reason = (
                f"Regime {result.regime} {direction}: "
                f"ADX={adx:.1f} (th={self.adx_trending}), "
                f"CHOP={chop:.1f} (rng_th={self.chop_ranging}), "
                f"ER={er:.3f}, ATR_ratio={atr_ratio:.2f}, "
                f"+DI={plus_di:.1f} -DI={minus_di:.1f}"
            )
        elif ranging:
            result.regime = REGIME_RANGING
            result.reason = (
                f"Regime RANGING (abstain): CHOP={chop:.1f} >= {self.chop_ranging}, "
                f"ER={er:.3f}, ADX={adx:.1f} — Trade Signal blocked by aggregator"
            )
        else:
            result.regime = "AMBIGUOUS"
            result.reason = (
                f"Regime ambiguous: ADX={adx:.1f}, CHOP={chop:.1f}, "
                f"ATR_ratio={atr_ratio:.2f} "
                f"(trending={trending}, ranging={ranging}, volatile={volatile})"
            )

        logger.debug(f"MarketRegimeDetector: {result.reason}")
        return result
