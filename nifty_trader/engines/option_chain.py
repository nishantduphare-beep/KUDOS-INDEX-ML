"""
engines/option_chain.py
Engine 3 — Option Chain Smart Money Detection

Reads institutional positioning through OI, PCR, and IV changes.

Bullish:  Put OI building + Call OI unwinding + PCR rising
Bearish:  Call OI building + Put OI unwinding + PCR falling
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
import numpy as np

import config
from data.structures import OptionChain

logger = logging.getLogger(__name__)


@dataclass
class OptionChainResult:
    is_triggered: bool = False
    direction: str = "NEUTRAL"
    strength: float = 0.0
    score: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    # Sub-conditions
    oi_buildup_signal: bool = False
    pcr_signal: bool = False
    volume_signal: bool = False


class OptionChainDetector:
    """
    Engine 3: Smart money detection via options positioning.

    Tracks how OI, PCR, and option volumes shift — reflecting
    institutional hedging or directional bets before moves.
    """

    def __init__(self):
        self.pcr_bull_th  = config.PCR_BULLISH_THRESHOLD    # 1.2
        self.pcr_bear_th  = config.PCR_BEARISH_THRESHOLD    # 0.8
        self.oi_sig_th    = config.OI_CHANGE_SIGNIFICANCE   # 0.10

    def evaluate(
        self,
        chain: OptionChain,
        prev_chain: Optional[OptionChain] = None
    ) -> OptionChainResult:
        result = OptionChainResult()

        if chain is None:
            result.reason = "No option chain data"
            return result

        # Staleness guard: skip if OC data is older than threshold
        age_sec = (datetime.now() - chain.timestamp).total_seconds()
        if age_sec > config.OC_STALENESS_THRESHOLD_SEC:
            result.reason = f"Option chain data stale ({age_sec:.0f}s old)"
            return result

        # ── Basic metrics ─────────────────────────────────────────
        pcr           = chain.pcr
        pcr_volume    = chain.pcr_volume
        total_call_oi = chain.total_call_oi
        total_put_oi  = chain.total_put_oi
        max_pain      = chain.max_pain
        spot          = chain.spot_price

        result.features.update({
            "pcr": round(pcr, 3),
            "pcr_volume": round(pcr_volume, 3),
            "total_call_oi": int(total_call_oi),
            "total_put_oi": int(total_put_oi),
            "max_pain": max_pain,
            "spot": spot,
            "max_pain_distance": round(spot - max_pain, 2),
        })

        # ── ATM-focused analysis ───────────────────────────────────
        atm_strikes = chain.get_atm_strikes(n=5)
        if not atm_strikes:
            result.reason = "No ATM strikes found"
            return result

        atm_call_oi = sum(s.call_oi for s in atm_strikes)
        atm_put_oi  = sum(s.put_oi  for s in atm_strikes)
        atm_pcr     = atm_put_oi / max(atm_call_oi, 1)

        # OI change: OI-data-fix — brokers return day-over-day OI change, not
        # intraday. When a previous chain snapshot is available we compute the
        # true intraday delta ourselves (current OI − previous snapshot OI).
        if prev_chain is not None and prev_chain.strikes:
            prev_map    = {s.strike: s for s in prev_chain.strikes}
            call_oi_ch  = sum(s.call_oi - (prev_map[s.strike].call_oi if s.strike in prev_map else s.call_oi)
                              for s in atm_strikes)
            put_oi_ch   = sum(s.put_oi  - (prev_map[s.strike].put_oi  if s.strike in prev_map else s.put_oi)
                              for s in atm_strikes)
        else:
            # First tick — no previous snapshot; broker day-over-day is the
            # best we have (noisy but better than ignoring it entirely).
            call_oi_ch = sum(s.call_oi_change for s in atm_strikes)
            put_oi_ch  = sum(s.put_oi_change  for s in atm_strikes)

        result.features.update({
            "atm_call_oi": int(atm_call_oi),
            "atm_put_oi": int(atm_put_oi),
            "atm_pcr": round(atm_pcr, 3),
            "call_oi_change": int(call_oi_ch),
            "put_oi_change": int(put_oi_ch),
        })

        # ── OI Change signals ─────────────────────────────────────
        # Normalize OI changes relative to existing OI.
        # Guard: if absolute ATM OI is too small (thin market), relative %
        # would be noise — treat as zero change to avoid false signals.
        _MIN_ATM_OI = config.OC_MIN_ATM_OI
        rel_call_ch = (call_oi_ch / max(atm_call_oi, 1)
                       if atm_call_oi >= _MIN_ATM_OI else 0.0)
        rel_put_ch  = (put_oi_ch  / max(atm_put_oi,  1)
                       if atm_put_oi  >= _MIN_ATM_OI else 0.0)

        # Bullish OI: Put OI building, Call OI reducing/neutral
        bullish_oi = (rel_put_ch > self.oi_sig_th) and (rel_call_ch < self.oi_sig_th / 2)
        # Bearish OI: Call OI building, Put OI reducing/neutral
        bearish_oi = (rel_call_ch > self.oi_sig_th) and (rel_put_ch < self.oi_sig_th / 2)

        result.features["rel_call_oi_change"] = round(rel_call_ch, 4)
        result.features["rel_put_oi_change"]  = round(rel_put_ch, 4)

        # ── PCR trend from prev chain ─────────────────────────────
        # Must be computed BEFORE pcr signal so bullish_pcr/bearish_pcr can use them.
        pcr_rising  = False
        pcr_falling = False
        if prev_chain is not None:
            prev_pcr  = prev_chain.pcr
            pcr_delta = pcr - prev_pcr
            pcr_rising  = pcr_delta >  0.05
            pcr_falling = pcr_delta < -0.05
            result.features["pcr_change"] = round(pcr_delta, 4)

        # ── PCR signal ────────────────────────────────────────────
        # WARNING-1 fix: PCR > 1.2 alone is not reliably BULLISH.
        # In a downtrend, high PCR means protective puts ARE being bought (bearish).
        # PCR level is only bullish signal when PCR is rising (fresh put writers
        # taking on new bullish risk) or at least NOT falling (hedges being unwound).
        # Same logic applies in reverse for bearish PCR.
        bullish_pcr = (pcr > self.pcr_bull_th) and not pcr_falling
        bearish_pcr = (pcr < self.pcr_bear_th) and not pcr_rising

        # ── Volume signal ─────────────────────────────────────────
        # Unusual option volume relative to OI
        atm_call_vol = sum(s.call_volume for s in atm_strikes)
        atm_put_vol  = sum(s.put_volume  for s in atm_strikes)
        vol_pcr = atm_put_vol / max(atm_call_vol, 1)
        bullish_vol = vol_pcr > 1.3
        bearish_vol = vol_pcr < 0.7
        result.features["vol_pcr"] = round(vol_pcr, 3)

        # ── IV analysis ───────────────────────────────────────────
        call_ivs = [s.call_iv for s in atm_strikes if s.call_iv > 0]
        put_ivs  = [s.put_iv  for s in atm_strikes if s.put_iv  > 0]
        avg_call_iv = np.mean(call_ivs) if call_ivs else 0
        avg_put_iv  = np.mean(put_ivs)  if put_ivs  else 0
        result.features["avg_call_iv"] = round(avg_call_iv, 2)
        result.features["avg_put_iv"]  = round(avg_put_iv, 2)

        # Max Pain pull — spot below max pain = bullish pull
        mp_pull = "BULLISH" if spot < max_pain else "BEARISH" if spot > max_pain else "NEUTRAL"
        result.features["max_pain_pull"] = mp_pull

        # ── Max pain pull (soft score bonus) ─────────────────────
        # Spot below max pain → gravitational pull upward (bullish bias)
        # Spot above max pain → gravitational pull downward (bearish bias)
        # Used as a 0.5-weight tiebreaker, not a hard condition.
        mp_bull = (mp_pull == "BULLISH")
        mp_bear = (mp_pull == "BEARISH")
        result.features["max_pain_bull"] = mp_bull
        result.features["max_pain_bear"] = mp_bear

        # ── Aggregate direction ───────────────────────────────────
        # Hard conditions (each = 1 vote): OI buildup, PCR level+direction, volume
        # Soft contributions (each = 0.5 vote): PCR trend direction, max pain pull
        bullish_score = (sum([bullish_oi, bullish_pcr, bullish_vol])
                         + (0.5 if pcr_rising  else 0)
                         + (0.5 if mp_bull     else 0))
        bearish_score = (sum([bearish_oi, bearish_pcr, bearish_vol])
                         + (0.5 if pcr_falling else 0)
                         + (0.5 if mp_bear     else 0))

        result.oi_buildup_signal = bullish_oi or bearish_oi
        result.pcr_signal = bullish_pcr or bearish_pcr
        result.volume_signal = bullish_vol or bearish_vol

        # Engine still requires 2 hard conditions to trigger (not just soft votes)
        conditions_met_bull = sum([bullish_oi, bullish_pcr, bullish_vol])
        conditions_met_bear = sum([bearish_oi, bearish_pcr, bearish_vol])

        if conditions_met_bull >= 2 and bullish_score > bearish_score:
            result.is_triggered = True
            result.direction    = "BULLISH"
            result.strength = min(1.0, conditions_met_bull / 3.0 +
                                  (0.1 if pcr_rising else 0) +
                                  (0.05 if mp_bull else 0))
        elif conditions_met_bear >= 2 and bearish_score > bullish_score:
            result.is_triggered = True
            result.direction    = "BEARISH"
            result.strength = min(1.0, conditions_met_bear / 3.0 +
                                  (0.1 if pcr_falling else 0) +
                                  (0.05 if mp_bear else 0))

        if result.is_triggered:
            result.score = round(result.strength * config.CONFIDENCE_WEIGHTS["option_chain"], 2)
            oi_src = "intraday" if (prev_chain is not None and prev_chain.strikes) else "day-over-day"
            result.reason = (
                f"Options {result.direction}: PCR={pcr:.2f} (mp_pull={mp_pull}), "
                f"ATM_PCR={atm_pcr:.2f}, "
                f"call_oi_ch={call_oi_ch:+,.0f}, put_oi_ch={put_oi_ch:+,.0f} [{oi_src}], "
                f"vol_pcr={vol_pcr:.2f}"
            )
        else:
            result.reason = (
                f"Options neutral: PCR={pcr:.2f} "
                f"bull_score={conditions_met_bull} bear_score={conditions_met_bear}"
            )

        logger.debug(f"OptionChainDetector: {result.reason}")
        return result

    def get_support_resistance(self, chain: OptionChain) -> Dict[str, float]:
        """
        Derive key S/R levels from OI.
        Max OI Call strike = resistance
        Max OI Put strike  = support
        """
        if not chain or not chain.strikes:
            return {"support": 0, "resistance": 0}

        max_call_oi_strike = max(chain.strikes, key=lambda s: s.call_oi)
        max_put_oi_strike  = max(chain.strikes, key=lambda s: s.put_oi)
        return {
            "support":    max_put_oi_strike.strike,
            "resistance": max_call_oi_strike.strike,
        }
