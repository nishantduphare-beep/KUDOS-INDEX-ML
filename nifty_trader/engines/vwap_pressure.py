"""
engines/vwap_pressure.py
Engine 7 — VWAP Pressure (Institutional Anchor)

VWAP (Volume Weighted Average Price) resets at 9:15 AM each day.
It is the single most-watched intraday level by institutional desks.

Signals:
  • VWAP Bounce   — price pulls back to VWAP mid-trend and reclaims it with volume
  • VWAP Reclaim  — price crosses above VWAP (was below) with a strong bullish candle
  • VWAP Rejection — price rises to VWAP from below, gets rejected with bearish candle
  • VWAP Cross Down — price crosses below VWAP with volume (trend flip)

All setups require:
  - Price within VWAP band (0.5×ATR or 0.3%, whichever is larger)
  - Clear candle body (body_ratio > 0.35)
  - Volume above average (volume_ratio >= 1.2)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)

# Proximity threshold to count as "touching" VWAP (fraction of ATR)
VWAP_TOUCH_ATR_MULT  = 0.5   # within 0.5×ATR counts as a VWAP touch
VWAP_TOUCH_PCT_MIN   = 0.003  # minimum 0.3% band (for low-ATR environments)
VWAP_BODY_MIN_RATIO  = 0.35   # candle body must be at least 35% of range
VWAP_VOL_RATIO_MIN   = 1.2    # volume must be 1.2× average


@dataclass
class VWAPResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    vwap_bounce: bool = False
    vwap_cross: bool = False
    vwap_rejection: bool = False


class VWAPPressureDetector:
    """
    Engine 7: VWAP-based institutional pressure detection.

    VWAP is computed fresh from today's session candles on every call.
    No external VWAP feed needed — calculated from open/high/low/close/volume.
    """

    def evaluate(self, df: pd.DataFrame) -> VWAPResult:
        result = VWAPResult()

        if df is None or len(df) < 5:
            result.reason = "Insufficient data"
            return result

        # ── Filter to today's session only ───────────────────────
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        today = df["timestamp"].iloc[-1].date()
        session_df = df[df["timestamp"].dt.date == today].copy()

        if len(session_df) < 3:
            result.reason = "Insufficient today session candles"
            result.features["vwap"] = 0.0
            return result

        # ── Compute VWAP from session start ───────────────────────
        typical = (session_df["high"] + session_df["low"] + session_df["close"]) / 3.0
        cum_tp_vol = (typical * session_df["volume"]).cumsum()
        cum_vol = session_df["volume"].cumsum().replace(0, np.nan)
        session_df["vwap"] = (cum_tp_vol / cum_vol).ffill()

        last     = session_df.iloc[-1]
        prev     = session_df.iloc[-2] if len(session_df) >= 2 else last

        vwap      = float(last["vwap"])
        close     = float(last["close"])
        prev_close = float(prev["close"])
        high      = float(last["high"])
        low       = float(last["low"])
        open_     = float(last["open"])
        atr       = float(df.iloc[-1].get("atr", close * 0.005)) or close * 0.005
        vol_ratio = float(last.get("volume_ratio", 1.0))

        # ── Distance from VWAP ────────────────────────────────────
        dist_abs  = close - vwap
        dist_pct  = (dist_abs / vwap * 100) if vwap > 0 else 0.0
        band      = max(atr * VWAP_TOUCH_ATR_MULT, vwap * VWAP_TOUCH_PCT_MIN)

        # Was the candle's range touching the VWAP band?
        touched_from_above = (low <= vwap + band) and (close > vwap)
        touched_from_below = (high >= vwap - band) and (close < vwap)

        # Did price cross VWAP this candle?
        cross_up   = prev_close < vwap <= close
        cross_down = prev_close > vwap >= close

        # ── Candle quality ────────────────────────────────────────
        candle_range = high - low
        body         = abs(close - open_)
        body_ratio   = body / max(candle_range, 1e-6)
        is_bullish   = close >= open_
        strong_body  = body_ratio >= VWAP_BODY_MIN_RATIO
        vol_ok       = vol_ratio >= VWAP_VOL_RATIO_MIN

        # ── Detect setups ─────────────────────────────────────────
        # BULLISH: price bounces/reclaims VWAP from below with volume
        bull_bounce = (touched_from_above or cross_up) and is_bullish and strong_body and vol_ok
        # BEARISH: price rejects at VWAP from above with volume
        bear_reject = (touched_from_below or cross_down) and not is_bullish and strong_body and vol_ok

        result.vwap_bounce    = bull_bounce
        result.vwap_cross     = cross_up or cross_down
        result.vwap_rejection = bear_reject

        # ── Save features (always) ────────────────────────────────
        result.features.update({
            "vwap":            round(vwap, 2),
            "dist_to_vwap_pct": round(dist_pct, 3),
            "vwap_cross_up":   bool(cross_up),
            "vwap_cross_down": bool(cross_down),
            "vwap_touch_band": round(band, 2),
            "vwap_body_ratio": round(body_ratio, 3),
            "vwap_vol_ratio":  round(vol_ratio, 3),
            "vwap_bounce":     bool(bull_bounce),
            "vwap_rejection":  bool(bear_reject),
        })

        # ── Trigger ───────────────────────────────────────────────
        if bull_bounce:
            result.is_triggered = True
            result.direction    = "BULLISH"
            setup_type = "cross_up" if cross_up else "bounce"
        elif bear_reject:
            result.is_triggered = True
            result.direction    = "BEARISH"
            setup_type = "cross_down" if cross_down else "rejection"
        else:
            result.reason = (
                f"No VWAP setup: vwap={vwap:.1f} close={close:.1f} "
                f"dist={dist_pct:+.2f}% body={body_ratio:.2f} vol={vol_ratio:.2f}x"
            )
            return result

        # ── Score ─────────────────────────────────────────────────
        # Cross > bounce (stronger signal); volume adds weight
        cross_bonus = 0.2 if result.vwap_cross else 0.0
        vol_bonus   = min(0.3, (vol_ratio - VWAP_VOL_RATIO_MIN) / 2.0)
        body_bonus  = min(0.2, (body_ratio - VWAP_BODY_MIN_RATIO) / 0.5)
        result.strength = min(1.0, 0.5 + cross_bonus + vol_bonus + body_bonus)
        result.score    = round(result.strength * config.CONFIDENCE_WEIGHTS.get("vwap_pressure", 15), 2)

        result.reason = (
            f"VWAP {result.direction} [{setup_type}]: "
            f"vwap={vwap:.1f} close={close:.1f} "
            f"dist={dist_pct:+.2f}% body={body_ratio:.2f} vol={vol_ratio:.2f}x"
        )
        logger.debug(f"VWAPPressureDetector: {result.reason}")
        return result
