"""
data/event_calendar.py
──────────────────────────────────────────────────────────────────
High-impact event calendar for Indian markets.

Option premiums spike before binary events and crush after — buying
options into these events has negative expectancy regardless of direction.
TRADE_SIGNALs are blocked during event windows. Early Move Alerts
still fire (ML data collection continues uninterrupted).

Events tracked:
  • RBI MPC policy decisions  — 6 per year, result day only
  • US Federal Reserve FOMC   — 8 per year, next Indian session open
  • Indian Union Budget        — Feb 1 each year, full session

Each event defines a block window within the Indian trading session.
config.EVENT_BLOCK_BEFORE_MINS / EVENT_BLOCK_AFTER_MINS add extra
buffer around the defined window.

To add your own events (earnings, state elections, etc.):
  Append to USER_EVENTS at the bottom of this file.
  Format: ("YYYY-MM-DD", "HH:MM_start", "HH:MM_end", "Event name")

Update sources:
  RBI MPC   → rbi.org.in/monetary-policy (published 3 months ahead)
  FOMC      → federalreserve.gov/monetarypolicy/fomccalendars.htm
  Budget    → always Feb 1 (Union Budget)
"""

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import config

# ──────────────────────────────────────────────────────────────────
# CACHED EVENTS (auto-updated weekly by event_updater.py)
# Loaded once at module import; refreshed in-process by calling
# reload_cache() after a background update completes.
# ──────────────────────────────────────────────────────────────────
_cached_events: Optional[List[Tuple[str, str, str, str]]] = None

def _load_cache() -> List[Tuple[str, str, str, str]]:
    """Load cached events from disk; return empty list on failure."""
    global _cached_events
    try:
        from data.event_updater import load_cache
        result = load_cache()
        if result:
            _cached_events = result
            return result
    except Exception:
        pass
    return []

def reload_cache():
    """Force reload from disk — called after a background update completes."""
    global _cached_events
    _cached_events = None
    _load_cache()

# ──────────────────────────────────────────────────────────────────
# BUILT-IN EVENT LIST
# Tuple: (date "YYYY-MM-DD", block_start "HH:MM", block_end "HH:MM", name)
#
# RBI MPC   — decision ~10:00–10:30 IST. Block 9:15–11:30 IST.
# FOMC      — Fed announces 2:00 PM ET = ~00:30 IST next morning.
#             Impact felt at Indian open. Block 9:15–10:00 of NEXT session.
# Budget    — presented 11:00 AM IST Feb 1. Block entire session.
# ──────────────────────────────────────────────────────────────────

_EVENTS: List[Tuple[str, str, str, str]] = [

    # ── RBI MPC Policy Decisions 2025 ────────────────────────────
    ("2025-04-09", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2025-06-06", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2025-08-07", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2025-10-08", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2025-12-05", "09:15", "11:30", "RBI MPC Policy Decision"),

    # ── RBI MPC Policy Decisions 2026 ────────────────────────────
    ("2026-02-06", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2026-04-07", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2026-06-05", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2026-08-06", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2026-10-07", "09:15", "11:30", "RBI MPC Policy Decision"),
    ("2026-12-04", "09:15", "11:30", "RBI MPC Policy Decision"),

    # ── US Federal Reserve FOMC 2025 ─────────────────────────────
    # Listed as the NEXT Indian session date after the ET announcement.
    ("2025-03-20", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-05-08", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-06-19", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-07-31", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-09-18", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-10-30", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2025-12-11", "09:15", "10:00", "US Fed FOMC Decision"),

    # ── US Federal Reserve FOMC 2026 ─────────────────────────────
    ("2026-01-29", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-03-19", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-05-07", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-06-18", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-07-30", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-09-17", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-11-05", "09:15", "10:00", "US Fed FOMC Decision"),
    ("2026-12-10", "09:15", "10:00", "US Fed FOMC Decision"),

    # ── Indian Union Budget ───────────────────────────────────────
    # Feb 1 each year. Full session block — IV spikes all day.
    ("2026-02-01", "09:15", "15:00", "Indian Union Budget"),
    ("2027-02-01", "09:15", "15:00", "Indian Union Budget"),
]


# ── User-defined custom events ─────────────────────────────────────
# Add earnings, state elections, special sessions, etc.
# Same format: ("YYYY-MM-DD", "HH:MM", "HH:MM", "Description")
USER_EVENTS: List[Tuple[str, str, str, str]] = []


# ──────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────

def _all_events() -> List[Tuple[str, str, str, str]]:
    """
    Merge priority: cached (auto-fetched) → hardcoded fallback → user events.
    Cache is loaded lazily on first call and reused for all subsequent ticks.
    """
    global _cached_events
    if _cached_events is None:
        _cached_events = _load_cache()
    # Use cached if non-empty, otherwise fall back to hardcoded _EVENTS
    source = _cached_events if _cached_events else _EVENTS
    return source + USER_EVENTS


def get_active_event(now_ist: Optional[datetime] = None) -> Optional[str]:
    """
    Returns the name of the active blocking event if current IST time falls
    inside any event window (including before/after buffers from config),
    else returns None.

    Called every tick by SignalAggregator — O(n) over event list, no I/O.
    """
    if not config.SIGNAL_BLOCK_ON_EVENT:
        return None

    if now_ist is None:
        now_ist = datetime.now(config.IST)

    today  = now_ist.date()
    before = timedelta(minutes=config.EVENT_BLOCK_BEFORE_MINS)
    after  = timedelta(minutes=config.EVENT_BLOCK_AFTER_MINS)

    for ev_date_str, start_str, end_str, name in _all_events():
        try:
            ev_date = date.fromisoformat(ev_date_str)
            if ev_date != today:
                continue
            h0, m0 = map(int, start_str.split(":"))
            h1, m1 = map(int, end_str.split(":"))
            block_start = now_ist.replace(hour=h0, minute=m0, second=0, microsecond=0) - before
            block_end   = now_ist.replace(hour=h1, minute=m1, second=0, microsecond=0) + after
            if block_start <= now_ist <= block_end:
                return name
        except Exception:
            continue
    return None


def is_event_window() -> bool:
    """True if current IST time is inside a high-impact event block window."""
    return get_active_event() is not None


def upcoming_events(days_ahead: int = 7) -> List[dict]:
    """
    Return events scheduled within the next N days.
    Used by UI to warn the user before market open.
    """
    today = date.today()
    result = []
    for ev_date_str, start_str, end_str, name in _all_events():
        try:
            ev_date = date.fromisoformat(ev_date_str)
            delta = (ev_date - today).days
            if 0 <= delta <= days_ahead:
                result.append({
                    "date":  ev_date_str,
                    "start": start_str,
                    "end":   end_str,
                    "name":  name,
                    "days_away": delta,
                })
        except Exception:
            continue
    return sorted(result, key=lambda x: x["date"])
