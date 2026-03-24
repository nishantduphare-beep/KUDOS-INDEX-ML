"""
data/base_api.py
─────────────────────────────────────────────────────────────────
Abstract base classes that define the CONTRACT every adapter must
implement.

Split into TWO interfaces deliberately:
  MarketDataAPI  — spot price + OHLCV candles only
  OptionsDataAPI — option chain, OI, PCR only

This separation means:
  • Each can be tested / mocked independently
  • A broker that only provides one type can be wired up partially
  • DataManager routes calls to the right interface
  • Future: run candles from Fyers + options from NSE directly
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from data.structures import Candle, OptionChain


# ──────────────────────────────────────────────────────────────────
# INTERFACE 1 — MARKET DATA  (candles + spot)
# ──────────────────────────────────────────────────────────────────

class MarketDataAPI(ABC):
    """
    Provides OHLCV candle history and live spot price.
    Implement this for every broker.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and establish session. Return True on success."""

    @abstractmethod
    def disconnect(self):
        """Clean up session / websocket."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if session is active."""

    @abstractmethod
    def get_spot_price(self, index_name: str) -> float:
        """
        Return the latest spot price for the index.
        index_name: one of NIFTY / BANKNIFTY / MIDCPNIFTY
        """

    @abstractmethod
    def get_historical_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        """
        Return `count` completed candles of `interval_minutes` duration.
        Most recent candle is last in the list.
        """

    def get_futures_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        """
        Return candles for the near-month futures contract.
        Volume in futures is real (unlike spot index which has zero volume).
        Default: return empty list (adapter may override).
        """
        return []

    def get_prev_day_close(self, index_name: str) -> float:
        """
        Return previous trading day's closing price.
        Used for day-change % display (matches broker/watchlist).
        Default: return 0.0 (adapter should override).
        """
        return 0.0

    def get_expiry_dates(self, index_name: str) -> list:
        """
        Return list of available expiry date strings for this index,
        nearest first (e.g. ["19MAR2025", "26MAR2025", ...]).
        Default: return empty list — adapters that support it should override.
        """
        return []

    def get_broker_name(self) -> str:
        return self.__class__.__name__.replace("MarketDataAPI", "").replace("Adapter", "")


# ──────────────────────────────────────────────────────────────────
# INTERFACE 2 — OPTIONS DATA  (chain + OI + IV)
# ──────────────────────────────────────────────────────────────────

class OptionsDataAPI(ABC):
    """
    Provides options chain data: OI, volume, IV, LTP per strike.
    May or may not share the same session as MarketDataAPI.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate (may reuse parent session token)."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if options data is accessible."""

    @abstractmethod
    def get_option_chain(self, index_name: str) -> OptionChain:
        """
        Return full option chain for the nearest weekly expiry.
        Must include at least ATM ±10 strikes.
        """

    def get_broker_name(self) -> str:
        return self.__class__.__name__.replace("OptionsDataAPI", "").replace("Adapter", "")


# ──────────────────────────────────────────────────────────────────
# COMBINED ADAPTER  (for brokers that handle both in one session)
# ──────────────────────────────────────────────────────────────────

class CombinedBrokerAdapter(MarketDataAPI, OptionsDataAPI):
    """
    Convenience base for brokers where market + options share one
    authentication session (Fyers, Dhan, Kite all work this way).

    Override connect() once — it covers both interfaces.
    """

    def connect(self) -> bool:
        raise NotImplementedError

    def disconnect(self):
        pass
