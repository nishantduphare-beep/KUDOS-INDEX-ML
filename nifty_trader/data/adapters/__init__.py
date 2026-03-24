"""
data/adapters/__init__.py
─────────────────────────────────────────────────────────────────
Adapter registry.

ACTIVE BROKERS:  fyers, mock
SLEEPING:        dhan, kite, upstox  (code preserved, not yet wired)

get_adapter(broker_name) returns a CombinedBrokerAdapter instance.
Sleeping brokers return SleepingAdapter — all methods are safe no-ops.
"""

from typing import Dict, Type
from data.base_api import CombinedBrokerAdapter
from data.structures import OptionChain
import logging

logger = logging.getLogger(__name__)

# ── Active brokers — only these connect to real APIs ──────────────
_ACTIVE_BROKERS = {"fyers", "mock"}

# ── Full registry — sleeping brokers point to their module but are
#    intercepted before instantiation. ──────────────────────────────
ADAPTER_REGISTRY: Dict[str, str] = {
    "fyers":  "data.adapters.fyers_adapter.FyersAdapter",
    "mock":   "data.adapters.mock_adapter.MockAdapter",
    # ── Sleeping — code intact, not active ─────────────────────────
    "dhan":   "data.adapters.dhan_adapter.DhanAdapter",
    "kite":   "data.adapters.kite_adapter.KiteAdapter",
    "upstox": "data.adapters.upstox_adapter.UpstoxAdapter",
}


# ──────────────────────────────────────────────────────────────────
# SleepingAdapter — safe no-op placeholder
# ──────────────────────────────────────────────────────────────────
class SleepingAdapter(CombinedBrokerAdapter):
    """
    Returned for brokers that are not yet active.
    All methods return safe empty values — never raises, never logs errors.
    The underlying adapter file is untouched; this just keeps it dormant.
    """

    def __init__(self, broker_name: str):
        self._name = broker_name

    def connect(self) -> bool:
        logger.info(
            f"[{self._name.upper()}] adapter is sleeping — "
            f"only Fyers is active. Returning False."
        )
        return False

    def disconnect(self):
        pass

    def is_connected(self) -> bool:
        return False

    def get_spot_price(self, index_name: str) -> float:
        return 0.0

    def get_historical_candles(self, index_name, interval_minutes=3, count=60):
        return []

    def get_futures_candles(self, index_name, interval_minutes=3, count=60):
        return []

    def get_prev_day_close(self, index_name: str) -> float:
        return 0.0

    def get_option_chain(self, index_name: str) -> OptionChain:
        return OptionChain(index_name, 0.0, "", [])

    def get_expiry_dates(self, index_name: str) -> list:
        return []

    def get_broker_name(self) -> str:
        return f"{self._name} (sleeping)"


# ──────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────
def get_adapter(broker_name: str) -> CombinedBrokerAdapter:
    """
    Return the adapter for broker_name.
    Sleeping brokers return SleepingAdapter without importing their module.
    Unknown brokers fall back to MockAdapter.
    """
    name = broker_name.lower()

    # Sleeping broker — return dormant adapter without touching the module
    if name not in _ACTIVE_BROKERS and name in ADAPTER_REGISTRY:
        logger.info(f"Broker '{name}' is sleeping — returning SleepingAdapter")
        return SleepingAdapter(name)

    module_path = ADAPTER_REGISTRY.get(name)

    if not module_path:
        logger.warning(f"Unknown broker '{broker_name}' — falling back to Mock")
        module_path = ADAPTER_REGISTRY["mock"]

    module_str, class_str = module_path.rsplit(".", 1)

    try:
        import importlib
        module = importlib.import_module(module_str)
        cls: Type[CombinedBrokerAdapter] = getattr(module, class_str)
        logger.info(f"Loaded adapter: {cls.__name__}")
        return cls()
    except ImportError as e:
        logger.error(f"Adapter import failed for '{broker_name}': {e} — using Mock")
        from data.adapters.mock_adapter import MockAdapter
        return MockAdapter()
    except Exception as e:
        logger.error(f"Adapter load error: {e} — using Mock")
        from data.adapters.mock_adapter import MockAdapter
        return MockAdapter()


def list_available_brokers() -> list:
    return list(ADAPTER_REGISTRY.keys())


def list_active_brokers() -> list:
    return list(_ACTIVE_BROKERS)


def is_broker_active(broker_name: str) -> bool:
    return broker_name.lower() in _ACTIVE_BROKERS
