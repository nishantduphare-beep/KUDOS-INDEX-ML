"""
data/structures.py
─────────────────────────────────────────────────────────────────
Canonical data structures shared across ALL adapters, data layers,
engines, and database modules.

Keeping them in one file ensures that any adapter (Fyers, Dhan, Kite,
Mock) returns identical objects — the rest of the system never needs
to know which broker produced the data.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
import config


# ──────────────────────────────────────────────────────────────────
# CANDLE
# ──────────────────────────────────────────────────────────────────

@dataclass
class Candle:
    index_name: str
    timestamp:  datetime
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     float = 0.0
    interval:   int   = 3        # minutes
    oi:         float = 0.0      # Open Interest (futures contracts only)

    # ── Derived properties ────────────────────────────────────────
    @property
    def candle_range(self) -> float:
        return self.high - self.low

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index_name":   self.index_name,
            "timestamp":    self.timestamp,
            "interval":     self.interval,
            "open":         self.open,
            "high":         self.high,
            "low":          self.low,
            "close":        self.close,
            "volume":       self.volume,
            "oi":           self.oi,
            "candle_range": self.candle_range,
            "body_size":    self.body_size,
            "upper_wick":   self.upper_wick,
            "lower_wick":   self.lower_wick,
            "is_bullish":   self.is_bullish,
        }


# ──────────────────────────────────────────────────────────────────
# OPTION STRIKE  (one row of an option chain)
# ──────────────────────────────────────────────────────────────────

@dataclass
class OptionStrike:
    strike:          float
    expiry:          str          # "27MAR2025"

    call_oi:         float = 0
    call_oi_change:  float = 0
    call_volume:     float = 0
    call_iv:         float = 0.0
    call_ltp:        float = 0.0
    call_delta:      float = 0.0
    call_gamma:      float = 0.0
    call_theta:      float = 0.0
    call_vega:       float = 0.0

    put_oi:          float = 0
    put_oi_change:   float = 0
    put_volume:      float = 0
    put_iv:          float = 0.0
    put_ltp:         float = 0.0
    put_delta:       float = 0.0
    put_gamma:       float = 0.0
    put_theta:       float = 0.0
    put_vega:        float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strike":         self.strike,
            "expiry":         self.expiry,
            "call_oi":        self.call_oi,
            "call_oi_change": self.call_oi_change,
            "call_volume":    self.call_volume,
            "call_iv":        self.call_iv,
            "call_ltp":       self.call_ltp,
            "call_delta":     self.call_delta,
            "call_gamma":     self.call_gamma,
            "call_theta":     self.call_theta,
            "call_vega":      self.call_vega,
            "put_oi":         self.put_oi,
            "put_oi_change":  self.put_oi_change,
            "put_volume":     self.put_volume,
            "put_iv":         self.put_iv,
            "put_ltp":        self.put_ltp,
            "put_delta":      self.put_delta,
            "put_gamma":      self.put_gamma,
            "put_theta":      self.put_theta,
            "put_vega":       self.put_vega,
        }


# ──────────────────────────────────────────────────────────────────
# OPTION CHAIN  (full chain for one index / expiry)
# ──────────────────────────────────────────────────────────────────

@dataclass
class OptionChain:
    index_name:       str
    spot_price:       float
    expiry:           str
    strikes:          List[OptionStrike]
    timestamp:        datetime = field(default_factory=datetime.now)
    next_expiry:      str = ""   # second-nearest expiry label, e.g. "03APR2025"
    next_expiry_unix: int = 0    # second-nearest expiry unix timestamp from broker

    # ── ATM ───────────────────────────────────────────────────────
    @property
    def atm_strike(self) -> float:
        gap = config.SYMBOL_MAP[self.index_name]["strike_gap"]
        return round(self.spot_price / gap) * gap

    # ── Aggregate OI ─────────────────────────────────────────────
    @property
    def total_call_oi(self) -> float:
        return sum(s.call_oi for s in self.strikes)

    @property
    def total_put_oi(self) -> float:
        return sum(s.put_oi for s in self.strikes)

    # ── PCR ───────────────────────────────────────────────────────
    @property
    def pcr(self) -> float:
        return self.total_put_oi / max(self.total_call_oi, 1)

    @property
    def pcr_volume(self) -> float:
        cv = sum(s.call_volume for s in self.strikes)
        pv = sum(s.put_volume  for s in self.strikes)
        return pv / max(cv, 1)

    # ── Max Pain ──────────────────────────────────────────────────
    @property
    def max_pain(self) -> float:
        min_pain_strike = None
        min_pain_value  = float("inf")
        for target in self.strikes:
            pain = sum(
                s.call_oi * max(0, target.strike - s.strike) +
                s.put_oi  * max(0, s.strike - target.strike)
                for s in self.strikes
            )
            if pain < min_pain_value:
                min_pain_value  = pain
                min_pain_strike = target.strike
        return min_pain_strike or self.atm_strike

    # ── ATM neighbourhood ─────────────────────────────────────────
    def get_atm_strikes(self, n: int = 5) -> List[OptionStrike]:
        atm = self.atm_strike
        gap = config.SYMBOL_MAP[self.index_name]["strike_gap"]
        return sorted(
            [s for s in self.strikes if abs(s.strike - atm) <= n * gap],
            key=lambda x: x.strike
        )

    def is_empty(self) -> bool:
        return len(self.strikes) == 0


# ──────────────────────────────────────────────────────────────────
# BROKER CONNECTION STATE  (used by UI credentials tab)
# ──────────────────────────────────────────────────────────────────

@dataclass
class BrokerConnectionState:
    broker_name:   str  = "none"
    is_connected:  bool = False
    is_auth_pending: bool = False       # waiting for OTP / redirect
    message:       str  = ""
    connected_at:  Optional[datetime] = None
    error:         str  = ""

    def set_connected(self, broker: str):
        self.broker_name  = broker
        self.is_connected = True
        self.is_auth_pending = False
        self.connected_at = datetime.now()
        self.message      = f"Connected to {broker}"
        self.error        = ""

    def set_error(self, msg: str):
        self.is_connected    = False
        self.is_auth_pending = False
        self.error           = msg
        self.message         = f"Error: {msg}"

    def set_pending(self, msg: str = "Waiting for authentication…"):
        self.is_auth_pending = True
        self.message         = msg
