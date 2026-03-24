"""
data/event_updater.py
──────────────────────────────────────────────────────────────────
Auto-fetches RBI MPC and US Fed FOMC event dates from official
websites and caches them locally.

Runs once per week in a background thread (non-blocking).
If all fetches fail, existing cache (or hardcoded fallback) is used.

Sources:
  FOMC  — federalreserve.gov/monetarypolicy/fomccalendars.htm
  RBI   — rbi.org.in/monetary-policy/mpc

Cache:
  data/events_cache.json  (auto-created, updated weekly)
"""

import json
import logging
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# CACHE FILE
# ──────────────────────────────────────────────────────────────────
_CACHE_FILE = Path(__file__).parent / "events_cache.json"
_UPDATE_INTERVAL_DAYS = 7   # re-fetch every week


# ──────────────────────────────────────────────────────────────────
# MONTH NAME → NUMBER
# ──────────────────────────────────────────────────────────────────
_MONTHS = {
    "january": 1,  "february": 2,  "march": 3,     "april": 4,
    "may": 5,      "june": 6,      "july": 7,       "august": 8,
    "september": 9,"october": 10,  "november": 11,  "december": 12,
    "jan": 1,      "feb": 2,       "mar": 3,        "apr": 4,
    "jun": 6,      "jul": 7,       "aug": 8,        "sep": 9,
    "oct": 10,     "nov": 11,      "dec": 12,
}


# ──────────────────────────────────────────────────────────────────
# CACHE I/O
# ──────────────────────────────────────────────────────────────────

def load_cache() -> Optional[List[Tuple[str, str, str, str]]]:
    """
    Load cached events list.
    Returns list of (date_str, start_str, end_str, name) tuples, or None.
    """
    try:
        if not _CACHE_FILE.exists():
            return None
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        fetched_at = data.get("fetched_at", "")
        events = data.get("events", [])
        logger.debug(f"Event cache loaded: {len(events)} events (fetched {fetched_at})")
        return [tuple(e) for e in events]
    except Exception as e:
        logger.warning(f"Event cache load failed: {e}")
        return None


def _save_cache(events: List[Tuple[str, str, str, str]]):
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.utcnow().isoformat(),
            "events": [list(e) for e in events],
        }
        _CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(f"Event cache saved: {len(events)} events → {_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Event cache save failed: {e}")


def needs_update() -> bool:
    """True if cache is missing or older than UPDATE_INTERVAL_DAYS."""
    try:
        if not _CACHE_FILE.exists():
            return True
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        return (datetime.utcnow() - fetched_at).days >= _UPDATE_INTERVAL_DAYS
    except Exception:
        return True


# ──────────────────────────────────────────────────────────────────
# FOMC PARSER
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
# Page lists meetings by year with date ranges like "January 28-29"
# Decision day = last day of the meeting range.
# We store the NEXT Indian trading day after the ET announcement
# (Fed announces ~2:00 PM ET = ~00:30 IST next morning).
# ──────────────────────────────────────────────────────────────────

_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

def _fetch_fomc_dates() -> List[Tuple[str, str, str, str]]:
    """Parse FOMC decision dates from the Federal Reserve website."""
    import requests
    resp = requests.get(
        _FOMC_URL, timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NiftyTrader/3.0)"}
    )
    resp.raise_for_status()
    html = resp.text
    events = []

    # ── Find year blocks ──────────────────────────────────────────
    # Split by year headings e.g. ">2025<" or "2025</h"
    year_split = re.split(r'(?=\b(20\d{2})\b)', html)
    current_year = None

    for chunk in year_split:
        year_match = re.match(r'^(20\d{2})$', chunk.strip())
        if year_match:
            current_year = int(year_match.group(1))
            continue
        if current_year is None:
            # Try to extract year from chunk header
            ym = re.search(r'\b(20[2-9]\d)\b', chunk[:100])
            if ym:
                current_year = int(ym.group(1))

        if current_year is None or current_year < date.today().year:
            continue

        # ── Extract meeting date ranges ───────────────────────────
        # Patterns: "January 28-29", "March 18–19", "April/May 30-1"
        pattern = (
            r'(January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+'
            r'(\d{1,2})\s*[-–]\s*(\d{1,2})'
        )
        for m in re.finditer(pattern, chunk, re.IGNORECASE):
            month_name = m.group(1).lower()
            # day1 = m.group(2) — meeting starts
            day2      = int(m.group(3))   # decision day (last day)
            month_num = _MONTHS.get(month_name)
            if not month_num:
                continue
            try:
                decision_date = date(current_year, month_num, day2)
            except ValueError:
                continue
            # Skip past decisions (no point blocking history)
            if decision_date < date.today():
                continue
            # The Fed announces at 2:00 PM ET ≈ 00:30 IST next morning.
            # Impact is felt at Indian market open — store the NEXT calendar day.
            indian_impact_date = decision_date + timedelta(days=1)
            events.append((
                indian_impact_date.isoformat(),
                "09:15", "10:00",
                "US Fed FOMC Decision",
            ))

    logger.info(f"FOMC parser: {len(events)} upcoming dates found")
    return events


# ──────────────────────────────────────────────────────────────────
# RBI MPC PARSER
# Source: rbi.org.in monetary policy page
# RBI announces MPC decisions at ~10:00 AM IST on the last meeting day.
# Block 9:15–11:30 IST on that day.
# ──────────────────────────────────────────────────────────────────

_RBI_URLS = [
    "https://www.rbi.org.in/monetary-policy/mpc",
    "https://rbi.org.in/monetary-policy/mpc",
    "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
]

def _fetch_rbi_dates() -> List[Tuple[str, str, str, str]]:
    """Parse RBI MPC decision dates from rbi.org.in."""
    import requests
    html = ""
    for url in _RBI_URLS:
        try:
            resp = requests.get(
                url, timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NiftyTrader/3.0)"}
            )
            if resp.status_code == 200:
                html = resp.text
                logger.debug(f"RBI page fetched from {url} ({len(html)} chars)")
                break
        except Exception as e:
            logger.debug(f"RBI fetch attempt {url}: {e}")
            continue

    if not html:
        logger.warning("RBI MPC page fetch failed — all URLs tried")
        return []

    events = []
    today  = date.today()

    # ── Pattern 1: "April 7-9, 2025" → decision = April 9 ────────
    # Matches: "Month D1-D2, YYYY" or "Month D1–D2, YYYY"
    p1 = (
        r'(January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+'
        r'(\d{1,2})\s*[-–]\s*(\d{1,2})[,\s]+(\d{4})'
    )
    for m in re.finditer(p1, html, re.IGNORECASE):
        month_name = m.group(1).lower()
        day2       = int(m.group(3))
        year       = int(m.group(4))
        month_num  = _MONTHS.get(month_name)
        if not month_num:
            continue
        try:
            decision_date = date(year, month_num, day2)
        except ValueError:
            continue
        if decision_date < today:
            continue
        events.append((
            decision_date.isoformat(),
            "09:15", "11:30",
            "RBI MPC Policy Decision",
        ))

    # ── Pattern 2: "DD Month YYYY to DD Month YYYY" ───────────────
    # E.g. "5 February 2025 to 7 February 2025" → decision = Feb 7
    p2 = (
        r'\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{4}\s+to\s+'
        r'(\d{1,2})\s+'
        r'(January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+(\d{4})'
    )
    for m in re.finditer(p2, html, re.IGNORECASE):
        day        = int(m.group(1))
        month_name = m.group(2).lower()
        year       = int(m.group(3))
        month_num  = _MONTHS.get(month_name)
        if not month_num:
            continue
        try:
            decision_date = date(year, month_num, day)
        except ValueError:
            continue
        if decision_date < today:
            continue
        events.append((
            decision_date.isoformat(),
            "09:15", "11:30",
            "RBI MPC Policy Decision",
        ))

    # ── Deduplicate by date ───────────────────────────────────────
    seen  = set()
    dedup = []
    for ev in events:
        if ev[0] not in seen:
            seen.add(ev[0])
            dedup.append(ev)

    logger.info(f"RBI MPC parser: {len(dedup)} upcoming dates found")
    return dedup


# ──────────────────────────────────────────────────────────────────
# BUDGET (fixed: always Feb 1, except when it falls on weekend)
# ──────────────────────────────────────────────────────────────────

def _budget_dates() -> List[Tuple[str, str, str, str]]:
    """Return Indian Union Budget dates for next 2 years (always Feb 1)."""
    events = []
    today = date.today()
    for year in range(today.year, today.year + 2):
        try:
            b = date(year, 2, 1)
            if b.weekday() == 5:   # Saturday → move to Monday Feb 3
                b = date(year, 2, 3)
            elif b.weekday() == 6: # Sunday → move to Monday Feb 2
                b = date(year, 2, 2)
            if b >= today:
                events.append((b.isoformat(), "09:15", "15:00", "Indian Union Budget"))
        except ValueError:
            pass
    return events


# ──────────────────────────────────────────────────────────────────
# MAIN UPDATE FUNCTION
# ──────────────────────────────────────────────────────────────────

def run_update() -> bool:
    """
    Fetch all event sources, merge, deduplicate and save to cache.
    Returns True on success (at least one source fetched).
    Called by start_background_updater() or manually for forced refresh.
    """
    logger.info("Event calendar update starting...")
    all_events: List[Tuple[str, str, str, str]] = []
    success = False

    # FOMC
    try:
        fomc = _fetch_fomc_dates()
        all_events.extend(fomc)
        success = True
    except Exception as e:
        logger.warning(f"FOMC fetch failed: {e}")

    # RBI MPC
    try:
        rbi = _fetch_rbi_dates()
        all_events.extend(rbi)
        success = True
    except Exception as e:
        logger.warning(f"RBI MPC fetch failed: {e}")

    # Budget (computed — always succeeds)
    all_events.extend(_budget_dates())

    # Deduplicate: same date + name → keep first
    seen   = set()
    merged = []
    for ev in sorted(all_events, key=lambda x: x[0]):
        key = (ev[0], ev[3])
        if key not in seen:
            seen.add(key)
            merged.append(ev)

    if merged:
        _save_cache(merged)
        logger.info(
            f"Event calendar updated: {len(merged)} events "
            f"({sum(1 for e in merged if 'FOMC' in e[3])} FOMC, "
            f"{sum(1 for e in merged if 'RBI' in e[3])} RBI, "
            f"{sum(1 for e in merged if 'Budget' in e[3])} Budget)"
        )
    else:
        logger.warning("Event calendar update: no events fetched from any source")

    return success


# ──────────────────────────────────────────────────────────────────
# BACKGROUND THREAD
# ──────────────────────────────────────────────────────────────────

_updater_thread: Optional[threading.Thread] = None


def start_background_updater():
    """
    Launch a daemon thread that updates the event cache on startup
    (if stale) and then every UPDATE_INTERVAL_DAYS days.

    Non-blocking — returns immediately.
    Safe to call multiple times (only one thread runs at a time).
    """
    global _updater_thread
    if _updater_thread and _updater_thread.is_alive():
        return

    def _loop():
        import time
        # Initial update if cache is stale
        if needs_update():
            try:
                run_update()
            except Exception as e:
                logger.error(f"Event calendar initial update error: {e}")
        # Then sleep and check weekly
        while True:
            time.sleep(86_400)  # check once per day
            if needs_update():
                try:
                    run_update()
                except Exception as e:
                    logger.error(f"Event calendar weekly update error: {e}")

    _updater_thread = threading.Thread(
        target=_loop,
        daemon=True,
        name="EventCalendarUpdater",
    )
    _updater_thread.start()
    logger.debug("Event calendar background updater started")
