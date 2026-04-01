"""
engines/setup_screener.py
─────────────────────────────────────────────────────────────────
Evaluates all 23 named setups against the current signal features.
Returns a list of SetupHit for every setup that fires this candle.

Called from SignalAggregator after all 8 engines have run.
Stateless — all context is passed in per call.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional

from ml.setups import SETUPS

logger = logging.getLogger(__name__)


@dataclass
class SetupHit:
    """One triggered setup for one candle."""
    setup_name:   str
    setup_grade:  str
    expected_wr:  float
    description:  str
    index_name:   str
    direction:    str
    timestamp:    datetime
    spot_price:   float
    atr:          float
    engines_count: int
    regime:       str
    volume_ratio: float
    pcr:          float
    alert_id:     int = 0    # filled by signal_aggregator before DB save


class SetupScreener:
    """
    Evaluates all named setups (from ml/setups.py) against the current
    signal features.  Thread-safe and stateless.
    """

    def evaluate(
        self,
        index_name:   str,
        direction:    str,
        timestamp:    datetime,
        spot_price:   float,
        atr:          float,
        engines_count: int,
        di_r,          # DIMomentumResult
        vol_r,         # VolumePressureResult
        oc_r,          # OptionChainResult
        regime_r,      # MarketRegimeResult
        vwap_r,        # VWAPResult
        mtf_r,         # MTFResult
        pcr: float = 0.0,
    ) -> List[SetupHit]:
        """
        Returns a list of SetupHit — one entry for every setup that fires.
        An empty list means no setup fired for this candle.
        """
        # Guard: any missing engine result → skip screener silently
        if di_r is None or vol_r is None or oc_r is None or regime_r is None or vwap_r is None or mtf_r is None:
            logger.debug("SetupScreener: one or more engine results are None — skipping")
            return []

        # Build flat feature dict from engine results
        plus_di  = float(di_r.features.get("plus_di",  0))
        minus_di = float(di_r.features.get("minus_di", 0))
        di_ratio = plus_di / minus_di if minus_di > 0 else 1.0

        features: Dict[str, Any] = {
            "index_name":             index_name,
            "direction":              direction,
            "engines_count":          engines_count,
            "regime":                 getattr(regime_r, "regime", ""),
            # DI
            "di_aligned": (
                (direction == "BULLISH" and plus_di > minus_di) or
                (direction == "BEARISH" and minus_di > plus_di)
            ),
            "di_ratio":               di_ratio,
            "plus_di":                plus_di,
            "minus_di":               minus_di,
            "adx":                    float(di_r.features.get("adx",       0)),
            "di_spread":              float(di_r.features.get("di_spread", 0)),
            "di_triggered":           bool(di_r.is_triggered),
            # Volume
            "volume_ratio":           float(vol_r.features.get("volume_ratio", 0)),
            "volume_triggered":       bool(vol_r.is_triggered),
            # Option chain
            "option_chain_triggered": bool(oc_r.is_triggered),
            "pcr":                    pcr,
            "iv_rank":                float(oc_r.features.get("avg_call_iv", 0)),
            # VWAP
            "vwap_triggered":         bool(vwap_r.is_triggered),
            # Regime
            "regime_triggered":       bool(regime_r.is_triggered),
            # MTF
            "mtf_alignment":          getattr(mtf_r, "alignment", "NEUTRAL"),
        }

        hits: List[SetupHit] = []
        for setup in SETUPS:
            if setup.matches(features):
                hits.append(SetupHit(
                    setup_name=setup.name,
                    setup_grade=setup.grade,
                    expected_wr=setup.expected_wr,
                    description=setup.description,
                    index_name=index_name,
                    direction=direction,
                    timestamp=timestamp,
                    spot_price=spot_price,
                    atr=atr,
                    engines_count=engines_count,
                    regime=features["regime"],
                    volume_ratio=features["volume_ratio"],
                    pcr=pcr,
                ))

        if hits:
            names = [h.setup_name for h in hits]
            logger.debug(
                f"SetupScreener [{index_name}] {direction}: "
                f"{len(hits)} setups fired — {names}"
            )

        return hits
