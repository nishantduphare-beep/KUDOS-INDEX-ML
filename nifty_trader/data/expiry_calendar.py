"""
data/expiry_calendar.py
Live expiry calendar — primary source is the broker (Fyers expiryData).

Two distinct expiry types:
  OPTIONS expiry  — weekly + monthly  (all dates in Fyers expiryData)
  FUTURES expiry  — monthly only      (last expiry of each calendar month)

In Indian markets:
  NIFTY      options: every Thursday    futures: last Thursday of month
  BANKNIFTY  options: every Wednesday   futures: last Wednesday of month
  SENSEX     options: every Friday      futures: last Friday of month
  MIDCPNIFTY options: last Tuesday/month futures: last Tuesday of month (same as options)

Flow:
  1. DataManager calls update_from_broker(index, expiry_dates_list) each time
     it fetches a fresh option chain. Dates come from Fyers expiryData[].date.
  2. update_from_broker() fills both caches:
       _option_expiry_cache  ← all dates (weekly + monthly)
       _futures_expiry_cache ← last date per calendar month (= futures expiry)
  3. All public functions read the live cache first.
  4. If cache is empty (mock / not yet connected), hardcoded weekday math is used
     as a best-effort fallback — never used in live trading once broker connects.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Live caches — populated by DataManager via update_from_broker()
# ──────────────────────────────────────────────────────────────────
_cache_lock = threading.Lock()   # guards both caches for thread-safe reads/writes
_option_expiry_cache:  Dict[str, List[date]] = {}   # all expiries (weekly + monthly)
_futures_expiry_cache: Dict[str, List[date]] = {}   # monthly-end expiries only


# ──────────────────────────────────────────────────────────────────
# Broker-facing update — called by DataManager on every OC refresh
# ──────────────────────────────────────────────────────────────────

def update_from_broker(index_name: str, expiry_dates: List[str]) -> None:
    """
    Parse ALL expiry date strings from Fyers expiryData and populate both caches.

    Options cache  ← every date in the list
    Futures cache  ← only the last expiry date of each calendar month
                     (monthly options and futures share the same end-of-month date)
    """
    parsed: List[date] = []
    for raw in expiry_dates:
        d = _parse_expiry_str(raw)
        if d:
            parsed.append(d)
    if not parsed:
        return

    parsed.sort()

    monthly_map: Dict[tuple, date] = {}
    for d in parsed:
        key = (d.year, d.month)
        if key not in monthly_map or d > monthly_map[key]:
            monthly_map[key] = d
    futures_list = sorted(monthly_map.values())

    with _cache_lock:
        _option_expiry_cache[index_name]  = parsed
        _futures_expiry_cache[index_name] = futures_list

    logger.debug(
        f"Expiry cache [{index_name}]: "
        f"options={[str(d) for d in parsed[:4]]} "
        f"futures={[str(d) for d in futures_list[:3]]}"
    )


def update_from_chain_expiry(index_name: str, expiry_str: str) -> None:
    """
    Convenience — update option cache from a single OptionChain.expiry string.
    Useful as fallback when get_expiry_dates() isn't supported by the adapter.
    """
    d = _parse_expiry_str(expiry_str)
    if not d:
        return
    with _cache_lock:
        existing = _option_expiry_cache.get(index_name, [])
        if d not in existing:
            _option_expiry_cache[index_name] = sorted(set(existing + [d]))
            # Rebuild futures cache inside the same lock
            _rebuild_futures_cache_locked(index_name)
            logger.debug(f"Expiry chain-update [{index_name}]: {d}")


# ──────────────────────────────────────────────────────────────────
# Public API — OPTIONS
# ──────────────────────────────────────────────────────────────────

def get_current_option_expiry(index_name: str, ref_date: date = None) -> date:
    """Nearest weekly option expiry >= ref_date."""
    today = ref_date or date.today()
    with _cache_lock:
        cache = list(_option_expiry_cache.get(index_name, []))
    for d in cache:
        if d >= today:
            return d
    return _hardcoded_option_expiry(index_name, today)


def is_option_expiry_day(index_name: str, ref_date: date = None) -> bool:
    today = ref_date or date.today()
    return get_current_option_expiry(index_name, today) == today


def days_to_option_expiry(index_name: str, ref_date: date = None) -> int:
    today = ref_date or date.today()
    return (get_current_option_expiry(index_name, today) - today).days


def all_option_expiries(index_name: str) -> List[date]:
    today = date.today()
    with _cache_lock:
        cache = list(_option_expiry_cache.get(index_name, []))
    return [d for d in cache if d >= today]


# ──────────────────────────────────────────────────────────────────
# Public API — FUTURES
# ──────────────────────────────────────────────────────────────────

def get_current_futures_expiry(index_name: str, ref_date: date = None) -> date:
    """Nearest monthly futures expiry >= ref_date."""
    today = ref_date or date.today()
    with _cache_lock:
        cache = list(_futures_expiry_cache.get(index_name, []))
    for d in cache:
        if d >= today:
            return d
    return _hardcoded_futures_expiry(index_name, today)


def is_futures_expiry_day(index_name: str, ref_date: date = None) -> bool:
    today = ref_date or date.today()
    return get_current_futures_expiry(index_name, today) == today


def days_to_futures_expiry(index_name: str, ref_date: date = None) -> int:
    today = ref_date or date.today()
    return (get_current_futures_expiry(index_name, today) - today).days


def all_futures_expiries(index_name: str) -> List[date]:
    today = date.today()
    with _cache_lock:
        cache = list(_futures_expiry_cache.get(index_name, []))
    return [d for d in cache if d >= today]


# ──────────────────────────────────────────────────────────────────
# Public API — Strategy helpers (use option expiry for weekly signals)
# ──────────────────────────────────────────────────────────────────

def is_pre_option_expiry_window(index_name: str, ref_date: date = None) -> bool:
    """Within PRE_EXPIRY_COLLECTION_DAYS of the next weekly option expiry."""
    return days_to_option_expiry(index_name, ref_date) <= config.PRE_EXPIRY_COLLECTION_DAYS


def is_pre_futures_expiry_window(index_name: str, ref_date: date = None) -> bool:
    """Within PRE_EXPIRY_COLLECTION_DAYS of the next monthly futures expiry."""
    return days_to_futures_expiry(index_name, ref_date) <= config.PRE_EXPIRY_COLLECTION_DAYS


def expiry_summary() -> Dict[str, dict]:
    """Full expiry info for all indices — used for logging and UI."""
    today = date.today()
    result = {}
    for idx in config.INDICES:
        opt_exp  = get_current_option_expiry(idx, today)
        fut_exp  = get_current_futures_expiry(idx, today)
        opt_dte  = (opt_exp - today).days
        fut_dte  = (fut_exp - today).days
        result[idx] = {
            "option_expiry":      opt_exp.strftime("%d %b %Y"),
            "option_dte":         opt_dte,
            "is_option_expiry":   opt_dte == 0,
            "pre_option_expiry":  opt_dte <= config.PRE_EXPIRY_COLLECTION_DAYS,
            "futures_expiry":     fut_exp.strftime("%d %b %Y"),
            "futures_dte":        fut_dte,
            "is_futures_expiry":  fut_dte == 0,
            "pre_futures_expiry": fut_dte <= config.PRE_EXPIRY_COLLECTION_DAYS,
            "source": "broker" if get_current_option_expiry(idx, today) != _hardcoded_option_expiry(idx, today) else "fallback",
        }
    return result


# ──────────────────────────────────────────────────────────────────
# Backwards-compatible aliases (used by signal_aggregator)
# ──────────────────────────────────────────────────────────────────

def is_expiry_day(index_name: str, ref_date: date = None) -> bool:
    """Alias: True if today is an OPTION expiry day for this index."""
    return is_option_expiry_day(index_name, ref_date)


def days_to_expiry(index_name: str, ref_date: date = None) -> int:
    """Alias: calendar days to the next OPTION expiry."""
    return days_to_option_expiry(index_name, ref_date)


def get_current_expiry(index_name: str, ref_date: date = None) -> date:
    """Alias: nearest OPTION expiry date."""
    return get_current_option_expiry(index_name, ref_date)


def is_pre_expiry_window(index_name: str, ref_date: date = None) -> bool:
    """Alias: within PRE_EXPIRY_COLLECTION_DAYS of next OPTION expiry."""
    return is_pre_option_expiry_window(index_name, ref_date)


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

_PARSE_FMTS = (
    "%d-%b-%Y",   # "19-Mar-2025"  ← Fyers primary format
    "%d%b%Y",     # "19MAR2025"
    "%Y-%m-%d",   # "2025-03-19"
    "%d-%m-%Y",   # "19-03-2025"
    "%d/%m/%Y",   # "19/03/2025"
    "%d %b %Y",   # "19 Mar 2025"
)


def _parse_expiry_str(raw: str) -> Optional[date]:
    if not raw:
        return None
    raw = raw.strip()
    for variant in (raw, raw.title(), raw.upper(), raw.lower()):
        for fmt in _PARSE_FMTS:
            try:
                return datetime.strptime(variant, fmt).date()
            except ValueError:
                continue
    logger.debug(f"expiry_calendar: could not parse '{raw}'")
    return None


def _rebuild_futures_cache_locked(index_name: str) -> None:
    """Rebuild futures cache from option cache. Caller MUST hold _cache_lock."""
    monthly_map: Dict[tuple, date] = {}
    for d in _option_expiry_cache.get(index_name, []):
        key = (d.year, d.month)
        if key not in monthly_map or d > monthly_map[key]:
            monthly_map[key] = d
    _futures_expiry_cache[index_name] = sorted(monthly_map.values())


# ── Hardcoded fallback weekday constants ──────────────────────────
_MON, _TUE, _WED, _THU, _FRI = 0, 1, 2, 3, 4

_OPTION_EXPIRY_WEEKDAY = {
    "NIFTY":      _THU,
    "BANKNIFTY":  _WED,
    "SENSEX":     _FRI,
    "MIDCPNIFTY": _TUE,
}

_FUTURES_EXPIRY_WEEKDAY = {
    "NIFTY":      _THU,   # last Thursday of month
    "BANKNIFTY":  _WED,   # last Wednesday of month
    "SENSEX":     _FRI,   # last Friday of month (BSE)
    "MIDCPNIFTY": _TUE,   # last Tuesday of month (same as options)
}


def _next_weekday(from_date: date, weekday: int) -> date:
    days_ahead = (weekday - from_date.weekday()) % 7
    return from_date + timedelta(days=days_ahead)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return last occurrence of `weekday` in the given month."""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    days_back = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=days_back)


def _hardcoded_option_expiry(index_name: str, today: date) -> date:
    """Weekly option expiry — used only when broker cache is empty."""
    weekday = _OPTION_EXPIRY_WEEKDAY.get(index_name, _THU)
    # MIDCPNIFTY has no weekly — return last-weekday-of-month
    if index_name == "MIDCPNIFTY":
        return _hardcoded_futures_expiry(index_name, today)
    return _next_weekday(today, weekday)


def _hardcoded_futures_expiry(index_name: str, today: date) -> date:
    """Monthly futures expiry — used only when broker cache is empty."""
    weekday = _FUTURES_EXPIRY_WEEKDAY.get(index_name, _THU)
    exp = _last_weekday_of_month(today.year, today.month, weekday)
    if exp < today:
        nxt = today.month + 1 if today.month < 12 else 1
        nyr = today.year if today.month < 12 else today.year + 1
        exp = _last_weekday_of_month(nyr, nxt, weekday)
    return exp
