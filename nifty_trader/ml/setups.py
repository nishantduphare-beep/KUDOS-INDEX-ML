"""
ml/setups.py
─────────────────────────────────────────────────────────────────
Named setup definitions based on 6-day live backtesting.
Each setup is an independent filter condition on signal features.

Usage:
  from ml.setups import SETUPS
  for setup in SETUPS:
      if setup.matches(features):
          ...

Win rates are from 6-day live data test (Mar 17-24 2026, n=4008).
These are starting estimates — they update as more data accumulates.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List

_log = logging.getLogger(__name__)


@dataclass
class Setup:
    name: str            # Short code  e.g. "S09_DI_TREND"
    description: str     # Human-readable explanation
    grade: str           # A++ / A+ / A / A- / B / C- / D / F
    expected_wr: float   # Tested win rate % (6-day live data)
    condition: Callable[[Dict[str, Any]], bool]

    # Optional filters — empty string means "all"
    index_filter: str    = ""   # e.g. "NIFTY" restricts to NIFTY only
    direction_filter: str = ""  # e.g. "BEARISH" restricts to bear signals

    def matches(self, features: Dict[str, Any]) -> bool:
        """
        Returns True if this setup fires for the given feature snapshot.
        Applies index_filter and direction_filter before condition check.
        """
        if self.index_filter and self.index_filter != features.get("index_name", ""):
            return False
        if self.direction_filter and self.direction_filter != features.get("direction", ""):
            return False
        try:
            return bool(self.condition(features))
        except (KeyError, TypeError) as e:
            _log.debug(f"Setup {self.name!r} eval error — bad feature key: {e}")
            return False
        except Exception as e:
            _log.debug(f"Setup {self.name!r} unexpected eval error: {e}")
            return False


# ─────────────────────────────────────────────────────────────────
# SETUP DEFINITIONS — 23 setups, ordered by expected win rate
# ─────────────────────────────────────────────────────────────────

SETUPS: List[Setup] = [

    # ── Tier F / D  (data collection only, below baseline) ───────

    Setup(
        name="S01_DI_ALIGNED",
        description="DI aligned with signal direction (3m)",
        grade="D",
        expected_wr=12.0,
        condition=lambda f: f["di_aligned"],
    ),

    Setup(
        name="S02_DI_RATIO",
        description="DI ratio strong bias (>1.2 bull / <0.8 bear)",
        grade="C-",
        expected_wr=19.2,
        condition=lambda f: (
            (f["direction"] == "BULLISH" and f["di_ratio"] > 1.2) or
            (f["direction"] == "BEARISH" and f["di_ratio"] < 0.8)
        ),
    ),

    Setup(
        name="S03_DI_E3",
        description="DI aligned + 3 or more engines triggered",
        grade="C-",
        expected_wr=19.2,
        condition=lambda f: f["di_aligned"] and f["engines_count"] >= 3,
    ),

    # ── Tier B (moderate edge) ────────────────────────────────────

    Setup(
        name="S04_DI_E4",
        description="DI aligned + 4 or more engines triggered",
        grade="B",
        expected_wr=40.1,
        condition=lambda f: f["di_aligned"] and f["engines_count"] >= 4,
    ),

    # ── Tier A- (single high-quality filter) ─────────────────────

    Setup(
        name="S05_TRENDING",
        description="Trending regime only (Chop+ADX+ATR combined)",
        grade="A-",
        expected_wr=55.8,
        condition=lambda f: f["regime"] == "TRENDING",
    ),

    Setup(
        name="S06_OC_ALONE",
        description="Option chain engine triggered alone",
        grade="A-",
        expected_wr=53.3,
        condition=lambda f: f["option_chain_triggered"],
    ),

    Setup(
        name="S07_OC_DI",
        description="Option chain triggered + DI aligned",
        grade="A-",
        expected_wr=56.3,
        condition=lambda f: f["option_chain_triggered"] and f["di_aligned"],
    ),

    Setup(
        name="S08_OC_TREND",
        description="Option chain triggered + Trending regime",
        grade="A-",
        expected_wr=53.6,
        condition=lambda f: f["option_chain_triggered"] and f["regime"] == "TRENDING",
    ),

    Setup(
        name="S17_E4_TREND",
        description="4+ engines triggered + Trending regime",
        grade="A-",
        expected_wr=55.8,
        condition=lambda f: f["engines_count"] >= 4 and f["regime"] == "TRENDING",
    ),

    Setup(
        name="S18_E4_OC",
        description="4+ engines triggered + OC triggered",
        grade="A-",
        expected_wr=53.3,
        condition=lambda f: f["engines_count"] >= 4 and f["option_chain_triggered"],
    ),

    # ── Tier A (strong combinations) ─────────────────────────────

    Setup(
        name="S09_DI_TREND",
        description="DI aligned + Trending regime — core best-balanced combo",
        grade="A",
        expected_wr=56.6,
        condition=lambda f: f["di_aligned"] and f["regime"] == "TRENDING",
    ),

    Setup(
        name="S10_OC_DI_TREND",
        description="OC triggered + DI aligned + Trending regime",
        grade="A",
        expected_wr=56.1,
        condition=lambda f: (
            f["option_chain_triggered"] and
            f["di_aligned"] and
            f["regime"] == "TRENDING"
        ),
    ),

    Setup(
        name="S12_NIFTY_DI_TREND",
        description="NIFTY only: DI aligned + Trending (62% WR)",
        grade="A",
        expected_wr=62.1,
        condition=lambda f: f["di_aligned"] and f["regime"] == "TRENDING",
        index_filter="NIFTY",
    ),

    Setup(
        name="S15_MIDCP_DI_TREND",
        description="MIDCPNIFTY only: DI aligned + Trending",
        grade="A",
        expected_wr=56.6,
        condition=lambda f: f["di_aligned"] and f["regime"] == "TRENDING",
        index_filter="MIDCPNIFTY",
    ),

    Setup(
        name="S16_SENSEX_BEAR_TREND",
        description="SENSEX bear signals only + Trending (58.5% WR)",
        grade="A",
        expected_wr=58.5,
        condition=lambda f: f["di_aligned"] and f["regime"] == "TRENDING",
        index_filter="SENSEX",
        direction_filter="BEARISH",
    ),

    Setup(
        name="S19_PCR_DI_TREND",
        description="PCR > 1.2 (put heavy) + DI aligned + Trending — bear confirmation",
        grade="A",
        expected_wr=60.1,
        condition=lambda f: (
            f["pcr"] > 1.2 and
            f["di_aligned"] and
            f["regime"] == "TRENDING"
        ),
        direction_filter="BEARISH",
    ),

    Setup(
        name="S21_MIDCP_OC_TREND",
        description="MIDCPNIFTY: OC + DI + Trending",
        grade="A",
        expected_wr=53.7,
        condition=lambda f: (
            f["option_chain_triggered"] and
            f["di_aligned"] and
            f["regime"] == "TRENDING"
        ),
        index_filter="MIDCPNIFTY",
    ),

    Setup(
        name="S23_DI_TREND_MTF",
        description="DI aligned + Trending + MTF STRONG (both 5m+15m agree)",
        grade="A",
        expected_wr=58.0,
        condition=lambda f: (
            f["di_aligned"] and
            f["regime"] == "TRENDING" and
            f["mtf_alignment"] == "STRONG"
        ),
    ),

    # ── Tier A+ (high win rate setups) ───────────────────────────

    Setup(
        name="S11_DI_TREND_VOL",
        description="DI aligned + Trending + High Volume (>1.5x) — 67% WR",
        grade="A+",
        expected_wr=67.2,
        condition=lambda f: (
            f["di_aligned"] and
            f["regime"] == "TRENDING" and
            f["volume_ratio"] >= 1.5
        ),
    ),

    Setup(
        name="S14_BNFTY_BEAR_TREND",
        description="BANKNIFTY bear only + Trending — 71% WR (bull blocked)",
        grade="A+",
        expected_wr=71.1,
        condition=lambda f: f["di_aligned"] and f["regime"] == "TRENDING",
        index_filter="BANKNIFTY",
        direction_filter="BEARISH",
    ),

    Setup(
        name="S22_BNFTY_OC_BEAR",
        description="BANKNIFTY: OC + DI + Trending (bear only) — 76.7% WR",
        grade="A+",
        expected_wr=76.7,
        condition=lambda f: (
            f["option_chain_triggered"] and
            f["di_aligned"] and
            f["regime"] == "TRENDING"
        ),
        index_filter="BANKNIFTY",
        direction_filter="BEARISH",
    ),

    # ── Tier A++ (best setups found) ─────────────────────────────

    Setup(
        name="S13_NIFTY_DI_TREND_VOL",
        description="NIFTY: DI + Trending + High Volume — 83.3% WR (best found)",
        grade="A++",
        expected_wr=83.3,
        condition=lambda f: (
            f["di_aligned"] and
            f["regime"] == "TRENDING" and
            f["volume_ratio"] >= 1.5
        ),
        index_filter="NIFTY",
    ),

    # ── Additional setups (needs more data to validate) ───────────

    Setup(
        name="S20_DI_TREND_VWAP",
        description="DI aligned + Trending + VWAP signal (needs more data)",
        grade="B",
        expected_wr=30.0,
        condition=lambda f: (
            f["di_aligned"] and
            f["regime"] == "TRENDING" and
            f["vwap_triggered"]
        ),
    ),
]

# Lookup by name for fast access
SETUP_MAP: Dict[str, Setup] = {s.name: s for s in SETUPS}
