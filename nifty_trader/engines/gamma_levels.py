"""
engines/gamma_levels.py
Engine 6 — Gamma Wall / Gamma Flip Detection

Market makers (MMs) who sold options must hedge their delta exposure.
At the strike with the highest open interest, MMs are maximally hedged.
This creates powerful support/resistance:

  Max Call OI strike = GAMMA WALL (resistance)
    → MMs buy the underlying as price rises, delta-hedge by selling above
      → price is repelled below this level

  Max Put OI strike = PUT WALL (support)
    → MMs sell the underlying as price falls, delta-hedge by buying below
      → price is supported above this level

Gamma Flip:
  When spot crosses through the gamma wall, MM hedging AMPLIFIES moves
  instead of dampening them → high-velocity breakout follows.

Signal logic:
  • Spot within PROXIMITY_PCT of Put Wall from above → BULLISH (put wall support)
  • Spot within PROXIMITY_PCT of Call Wall from below → BEARISH (call wall resistance)
  • Spot just crossed gamma wall (vs prev_chain) → direction of crossing
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import numpy as np

import config
from data.structures import OptionChain

logger = logging.getLogger(__name__)


@dataclass
class GammaLevelsResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    near_put_wall: bool = False      # Spot near max Put OI → BULLISH support
    near_call_wall: bool = False     # Spot near max Call OI → BEARISH resistance
    gamma_flip: bool = False         # Spot crossed gamma wall → amplified move


class GammaLevelsDetector:
    """
    Engine 6: Gamma wall and gamma flip detection.

    Identifies where market-maker hedging creates magnetic support/resistance
    and detects the moment the gamma flip triggers explosive directional moves.
    """

    def __init__(self):
        self.proximity_pct = config.GAMMA_WALL_PROXIMITY_PCT   # 0.005 (0.5%)
        self.flip_pct      = config.GAMMA_FLIP_PROXIMITY_PCT   # 0.002 (0.2%)

    def evaluate(
        self,
        chain: OptionChain,
        prev_chain: Optional[OptionChain] = None
    ) -> GammaLevelsResult:
        result = GammaLevelsResult()

        if chain is None or not chain.strikes:
            result.reason = "No option chain data"
            return result

        spot = chain.spot_price
        if spot <= 0:
            result.reason = "Invalid spot price"
            return result

        # ── Find gamma walls ──────────────────────────────────────
        max_call_oi_strike = max(chain.strikes, key=lambda s: s.call_oi)
        max_put_oi_strike  = max(chain.strikes, key=lambda s: s.put_oi)

        call_wall = max_call_oi_strike.strike
        put_wall  = max_put_oi_strike.strike

        # Max gamma level = strike with highest combined OI
        gamma_wall_strike = max(
            chain.strikes,
            key=lambda s: s.call_oi + s.put_oi
        ).strike

        # ── Compute distances ──────────────────────────────────────
        dist_to_call_wall = (call_wall - spot) / spot   # positive = spot below call wall
        dist_to_put_wall  = (spot - put_wall)  / spot   # positive = spot above put wall
        dist_to_gamma_wall= abs(spot - gamma_wall_strike) / spot

        result.features.update({
            "call_wall":          call_wall,
            "put_wall":           put_wall,
            "gamma_wall":         gamma_wall_strike,
            "spot":               round(spot, 2),
            "dist_to_call_wall":  round(dist_to_call_wall, 4),
            "dist_to_put_wall":   round(dist_to_put_wall, 4),
            "dist_to_gamma_wall": round(dist_to_gamma_wall, 4),
            "max_call_oi":        int(max_call_oi_strike.call_oi),
            "max_put_oi":         int(max_put_oi_strike.put_oi),
        })

        # ── Condition 1: Near Put Wall (bullish support) ──────────
        # Spot is just above the put wall (within proximity_pct)
        if 0 <= dist_to_put_wall <= self.proximity_pct:
            result.near_put_wall = True

        # ── Condition 2: Near Call Wall (bearish resistance) ───────
        # Spot is just below the call wall (within proximity_pct)
        if 0 <= dist_to_call_wall <= self.proximity_pct:
            result.near_call_wall = True

        # ── Condition 3: Gamma Flip ────────────────────────────────
        if prev_chain is not None and prev_chain.spot_price > 0:
            prev_spot = prev_chain.spot_price
            # Check if spot crossed the gamma wall level between readings
            crossed_up   = prev_spot < gamma_wall_strike <= spot
            crossed_down = prev_spot > gamma_wall_strike >= spot

            if crossed_up or crossed_down:
                result.gamma_flip = True
                result.features["gamma_flip_direction"] = "UP" if crossed_up else "DOWN"
                result.features["prev_spot"] = round(prev_spot, 2)

        # ── Aggregate ─────────────────────────────────────────────
        if result.gamma_flip:
            flip_dir = result.features.get("gamma_flip_direction", "UP")
            result.is_triggered = True
            result.direction    = "BULLISH" if flip_dir == "UP" else "BEARISH"
            # Gamma flip is a strong signal; clamp so it never goes below 0.5
            proximity_ratio = dist_to_gamma_wall / max(self.proximity_pct, 1e-6)
            result.strength = min(1.0, max(0.5, 0.75 + (1 - proximity_ratio) * 0.25))

        elif result.near_put_wall and not result.near_call_wall:
            result.is_triggered = True
            result.direction    = "BULLISH"
            proximity_score     = 1.0 - (dist_to_put_wall / self.proximity_pct)
            result.strength     = min(1.0, 0.5 + proximity_score * 0.4)

        elif result.near_call_wall and not result.near_put_wall:
            result.is_triggered = True
            result.direction    = "BEARISH"
            proximity_score     = 1.0 - (dist_to_call_wall / self.proximity_pct)
            result.strength     = min(1.0, 0.5 + proximity_score * 0.4)

        if result.is_triggered:
            result.score = round(
                result.strength * config.CONFIDENCE_WEIGHTS["gamma_levels"], 2
            )
            result.reason = (
                f"Gamma {result.direction}: "
                f"call_wall={call_wall:.0f}, put_wall={put_wall:.0f}, "
                f"spot={spot:.0f}, "
                f"gamma_flip={result.gamma_flip}, "
                f"near_put={result.near_put_wall}, near_call={result.near_call_wall}"
            )
        else:
            result.reason = (
                f"No gamma signal: "
                f"dist_call={dist_to_call_wall:.3f}, dist_put={dist_to_put_wall:.3f}, "
                f"proximity_th={self.proximity_pct}"
            )

        logger.debug(f"GammaLevelsDetector: {result.reason}")
        return result
