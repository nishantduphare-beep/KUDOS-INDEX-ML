"""
data/adapters/kite_adapter.py
─────────────────────────────────────────────────────────────────
Zerodha Kite Connect v3 adapter — full OAuth + token lifecycle.

Auth flow:
  1. generate_auth_url() → open browser → user logs in
  2. Kite redirects with ?request_token=XXXX in the URL
  3. exchange_request_token(token) → saves access_token to disk
  4. Token expires at 6am IST next day (Kite's policy)
  5. Next launch: auto-load if not expired, else prompt for new token

Option chain note:
  Kite has no native option chain endpoint. We fetch NFO instruments
  once per session, filter to nearest weekly expiry and ATM ±range,
  then batch-quote the relevant symbols.

Install: pip install kiteconnect
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import List, Optional, Dict, Callable

import config
from data.base_api import CombinedBrokerAdapter
from data.structures import Candle, OptionChain, OptionStrike

logger = logging.getLogger(__name__)

TOKEN_FILE = Path("auth/kite_token.json")

# NSE index instrument tokens for historical data
_INSTRUMENT_TOKENS = {
    "NIFTY":      256265,
    "BANKNIFTY":  260105,
    "MIDCPNIFTY": 288009,
}

# Symbols for LTP quotes
_LTP_SYMBOLS = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
}

# NFO instrument name prefix used in instruments CSV
_NFO_NAME = {
    "NIFTY":      "NIFTY",
    "BANKNIFTY":  "BANKNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
}

# Kite interval strings
_INTERVAL_MAP = {
    1: "minute", 3: "3minute", 5: "5minute",
    10: "10minute", 15: "15minute", 30: "30minute", 60: "60minute",
}


# ──────────────────────────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────────────────────────

def _next_6am_ist_utc() -> datetime:
    """Kite tokens expire at 6:00 AM IST the next day."""
    _IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(_IST)
    next_day = (now_ist + timedelta(days=1)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    return next_day.astimezone(timezone.utc)


def _save_kite_token(access_token: str, api_key: str):
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    exp = _next_6am_ist_utc()
    payload = {
        "access_token": access_token,
        "api_key":      api_key,
        "saved_at":     datetime.utcnow().isoformat(),
        "expires_at":   exp.isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    config.BROKER_CREDENTIALS["kite"]["access_token"] = access_token
    logger.info(f"Kite token saved — expires {exp.strftime('%d %b %Y %H:%M UTC')}")


def _load_kite_token() -> Optional[Dict]:
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        exp  = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if (exp - datetime.now(timezone.utc)).total_seconds() > 300:
            return data
        logger.info("Kite token expired")
    except Exception as e:
        logger.warning(f"Kite token read error: {e}")
    return None


def kite_token_expiry_display() -> str:
    data = _load_kite_token()
    if not data:
        return "No valid token"
    try:
        exp = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo:
            _IST = timezone(timedelta(hours=5, minutes=30))
            exp_ist   = exp.astimezone(_IST)
            remaining = exp - datetime.now(timezone.utc)
            h, m      = divmod(int(remaining.total_seconds()) // 60, 60)
            return f"Expires {exp_ist.strftime('%d %b %H:%M IST')}  ({h}h {m}m left)"
    except Exception:
        pass
    return "Token loaded"


# ──────────────────────────────────────────────────────────────────
# KiteAdapter
# ──────────────────────────────────────────────────────────────────

class KiteAdapter(CombinedBrokerAdapter):

    def __init__(self):
        self._kite                = None
        self._connected           = False
        self._creds               = config.BROKER_CREDENTIALS.get("kite", {})
        self._instruments_cache:  Optional[List] = None
        self._auth_url_cb:        Optional[Callable[[str], None]] = None

    # ── UI callback ───────────────────────────────────────────────
    def set_auth_url_callback(self, fn: Callable[[str], None]):
        self._auth_url_cb = fn

    def needs_auth(self) -> bool:
        return _load_kite_token() is None

    def token_expiry_display(self) -> str:
        return kite_token_expiry_display()

    # ── Step 1: Auth URL ──────────────────────────────────────────
    def generate_auth_url(self) -> str:
        self._creds = config.BROKER_CREDENTIALS.get("kite", {})
        api_key = self._creds.get("api_key", "")
        try:
            from kiteconnect import KiteConnect  # type: ignore
            kite = KiteConnect(api_key=api_key)
            url  = kite.login_url()
            logger.info("Kite auth URL generated")
            if self._auth_url_cb:
                self._auth_url_cb(url)
            return url
        except ImportError:
            raise ImportError("Run: pip install kiteconnect")

    # ── Step 2: Exchange request token ────────────────────────────
    def exchange_request_token(self, request_token: str) -> bool:
        self._creds    = config.BROKER_CREDENTIALS.get("kite", {})
        api_key        = self._creds.get("api_key", "")
        api_secret     = self._creds.get("api_secret", "")
        try:
            from kiteconnect import KiteConnect  # type: ignore
            kite    = KiteConnect(api_key=api_key)
            session = kite.generate_session(request_token, api_secret=api_secret)
            token   = session["access_token"]
            _save_kite_token(token, api_key)
            return self._init_session(api_key, token)
        except Exception as e:
            logger.error(f"Kite token exchange error: {e}")
            return False

    # ── Step 2b: Direct token paste ───────────────────────────────
    def set_token_direct(self, token: str) -> bool:
        self._creds = config.BROKER_CREDENTIALS.get("kite", {})
        api_key     = self._creds.get("api_key", "")
        _save_kite_token(token, api_key)
        return self._init_session(api_key, token)

    # ── Session init ──────────────────────────────────────────────
    def _init_session(self, api_key: str, access_token: str) -> bool:
        try:
            from kiteconnect import KiteConnect  # type: ignore
            self._kite = KiteConnect(api_key=api_key)
            self._kite.set_access_token(access_token)
            profile = self._kite.profile()
            logger.info(f"Kite active — {profile.get('user_name', '')}")
            self._connected           = True
            self._instruments_cache   = None  # reset on new session
            return True
        except Exception as e:
            logger.error(f"Kite session error: {e}")
            return False

    # ── CombinedBrokerAdapter interface ───────────────────────────

    def connect(self) -> bool:
        self._creds = config.BROKER_CREDENTIALS.get("kite", {})
        cached = _load_kite_token()
        if cached:
            return self._init_session(
                cached.get("api_key", self._creds.get("api_key", "")),
                cached["access_token"]
            )
        token   = self._creds.get("access_token", "")
        api_key = self._creds.get("api_key", "")
        if token and api_key:
            ok = self._init_session(api_key, token)
            if ok:
                _save_kite_token(token, api_key)
            return ok
        logger.info("Kite: auth required — call generate_auth_url()")
        return False

    def disconnect(self):
        try:
            if self._kite:
                self._kite.invalidate_access_token()
        except Exception:
            pass
        self._connected = False
        self._kite      = None

    def is_connected(self) -> bool:
        return self._connected

    # ── Market Data ───────────────────────────────────────────────

    def get_spot_price(self, index_name: str) -> float:
        sym = _LTP_SYMBOLS[index_name]
        try:
            ltp = self._kite.ltp([sym])
            return float(ltp[sym]["last_price"])
        except Exception as e:
            logger.error(f"Kite spot [{index_name}]: {e}")
            return 0.0

    def get_historical_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        token    = _INSTRUMENT_TOKENS[index_name]
        interval = _INTERVAL_MAP.get(interval_minutes, "3minute")
        from_dt  = datetime.now() - timedelta(days=5)
        to_dt    = datetime.now()
        try:
            data = self._kite.historical_data(
                token, from_dt, to_dt, interval,
                continuous=False, oi=False,
            )
            candles = [
                Candle(
                    index_name=index_name,
                    timestamp=d["date"] if isinstance(d["date"], datetime) else datetime.fromisoformat(str(d["date"])),
                    open=float(d["open"]),
                    high=float(d["high"]),
                    low=float(d["low"]),
                    close=float(d["close"]),
                    volume=float(d.get("volume", 0)),
                    interval=interval_minutes,
                )
                for d in data
            ]
            return candles[-count:]
        except Exception as e:
            logger.error(f"Kite candles [{index_name}]: {e}")
            return []

    # ── Options Data ──────────────────────────────────────────────

    def get_option_chain(self, index_name: str) -> OptionChain:
        """
        Build option chain via Kite instruments + batch quotes.
        Kite has no single option chain endpoint, so we:
          1. Fetch NFO instruments once per session (cached)
          2. Filter to the index and nearest weekly expiry
          3. Batch-quote all relevant strike symbols
          4. Assemble OptionChain
        """
        spot = self.get_spot_price(index_name)
        if spot == 0.0:
            return OptionChain(index_name, spot, "", [])

        gap    = config.SYMBOL_MAP[index_name]["strike_gap"]
        atm    = round(spot / gap) * gap
        prefix = _NFO_NAME[index_name]

        try:
            # Lazy-load + cache NFO instrument list (refreshes on new session)
            if self._instruments_cache is None:
                logger.info("Kite: fetching NFO instruments list")
                self._instruments_cache = self._kite.instruments("NFO")

            # Filter to this index's CE/PE options
            opts = [
                i for i in self._instruments_cache
                if i["name"] == prefix
                and i["instrument_type"] in ("CE", "PE")
            ]
            if not opts:
                logger.warning(f"Kite: no NFO options found for {index_name}")
                return OptionChain(index_name, spot, "", [])

            # Nearest expiry
            expiries = sorted(set(i["expiry"] for i in opts if i.get("expiry")))
            if not expiries:
                return OptionChain(index_name, spot, "", [])
            nearest_expiry = expiries[0]

            # ATM ± strike range
            strike_range = config.ATM_STRIKE_RANGE * gap
            relevant = [
                i for i in opts
                if i["expiry"] == nearest_expiry
                and abs(float(i["strike"]) - atm) <= strike_range
            ]
            if not relevant:
                return OptionChain(index_name, spot, "", [])

            # Batch quote — Kite allows up to 500 symbols per call
            symbols = [f"NFO:{i['tradingsymbol']}" for i in relevant]
            quotes: Dict = {}
            for chunk in [symbols[k:k + 500] for k in range(0, len(symbols), 500)]:
                quotes.update(self._kite.quote(chunk))

            # Build per-strike dict
            strike_map: Dict[float, Dict] = {}
            for inst in relevant:
                s        = float(inst["strike"])
                opt_type = inst["instrument_type"]          # "CE" or "PE"
                sym_key  = f"NFO:{inst['tradingsymbol']}"
                q        = quotes.get(sym_key, {})

                oi           = float(q.get("oi", 0))
                oi_day_high  = float(q.get("oi_day_high", oi))
                oi_day_low   = float(q.get("oi_day_low",  oi))
                oi_change    = oi_day_high - oi_day_low
                volume       = float(q.get("volume", 0))
                ltp          = float(q.get("last_price", 0))

                if s not in strike_map:
                    strike_map[s] = {}
                strike_map[s][opt_type] = {
                    "oi": oi, "oi_change": oi_change,
                    "volume": volume, "ltp": ltp, "iv": 0.0,
                }

            # Convert to OptionStrike list
            expiry_str = (
                nearest_expiry.strftime("%d%b%Y").upper()
                if hasattr(nearest_expiry, "strftime")
                else str(nearest_expiry)
            )
            strikes = []
            for s_price in sorted(strike_map):
                d  = strike_map[s_price]
                ce = d.get("CE", {})
                pe = d.get("PE", {})
                strikes.append(OptionStrike(
                    strike=s_price,
                    expiry=expiry_str,
                    call_oi=ce.get("oi", 0),
                    call_oi_change=ce.get("oi_change", 0),
                    call_volume=ce.get("volume", 0),
                    call_iv=ce.get("iv", 0.0),
                    call_ltp=ce.get("ltp", 0.0),
                    put_oi=pe.get("oi", 0),
                    put_oi_change=pe.get("oi_change", 0),
                    put_volume=pe.get("volume", 0),
                    put_iv=pe.get("iv", 0.0),
                    put_ltp=pe.get("ltp", 0.0),
                ))

            return OptionChain(index_name, spot, expiry_str, strikes)

        except Exception as e:
            logger.error(f"Kite option chain [{index_name}]: {e}")
            return OptionChain(index_name, spot, "", [])
