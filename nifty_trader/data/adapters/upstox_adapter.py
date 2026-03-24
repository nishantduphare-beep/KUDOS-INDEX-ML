"""
data/adapters/upstox_adapter.py
─────────────────────────────────────────────────────────────────
Upstox API v2 adapter — OAuth 2.0 PKCE + full market data.

Auth flow:
  1. generate_auth_url() → open browser → user logs in
  2. Upstox redirects to redirect_uri with ?code=XXXX
  3. exchange_auth_code(code) → saves access_token to disk
  4. Token valid until 3:30 AM IST next day
  5. Next launch: auto-load if not expired, else prompt

Redirect URI: must be registered in Upstox developer portal.
Default: http://localhost:8888/callback

Install: pip install upstox-python-sdk  OR  use requests (no SDK needed,
         this adapter uses the REST API directly to avoid SDK complexity)
"""

import json
import logging
import secrets
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Callable

import requests

import config
from data.base_api import CombinedBrokerAdapter
from data.structures import Candle, OptionChain, OptionStrike

logger = logging.getLogger(__name__)

TOKEN_FILE    = Path("auth/upstox_token.json")
UPSTOX_API    = "https://api.upstox.com/v2"
REDIRECT_URI  = "http://localhost:8888/callback"

# Upstox instrument keys for NSE indices
_INSTRUMENT_KEYS = {
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MIDCAP SELECT",
}

# Historical interval strings (Upstox v2)
_INTERVAL_MAP = {
    1:  "1minute",
    3:  "3minute",
    5:  "5minute",
    10: "10minute",
    15: "15minute",
    30: "30minute",
    60: "60minute",
}

# Option chain index keys for Upstox
_OPTION_CHAIN_KEYS = {
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MIDCAP SELECT",
}


# ──────────────────────────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────────────────────────

def _next_330am_ist_utc() -> datetime:
    """Upstox tokens expire at 3:30 AM IST the next day."""
    _IST = timezone(timedelta(hours=5, minutes=30))
    now_ist  = datetime.now(_IST)
    next_day = (now_ist + timedelta(days=1)).replace(
        hour=3, minute=30, second=0, microsecond=0
    )
    return next_day.astimezone(timezone.utc)


def _save_upstox_token(access_token: str):
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    exp = _next_330am_ist_utc()
    payload = {
        "access_token": access_token,
        "saved_at":     datetime.utcnow().isoformat(),
        "expires_at":   exp.isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    config.BROKER_CREDENTIALS["upstox"]["access_token"] = access_token
    logger.info(f"Upstox token saved — expires {exp.strftime('%d %b %Y %H:%M UTC')}")


def _load_upstox_token() -> Optional[Dict]:
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        exp  = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if (exp - datetime.now(timezone.utc)).total_seconds() > 300:
            return data
        logger.info("Upstox token expired")
    except Exception as e:
        logger.warning(f"Upstox token read error: {e}")
    return None


def upstox_token_expiry_display() -> str:
    data = _load_upstox_token()
    if not data:
        return "No valid token"
    try:
        exp = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo:
            _IST      = timezone(timedelta(hours=5, minutes=30))
            exp_ist   = exp.astimezone(_IST)
            remaining = exp - datetime.now(timezone.utc)
            h, m      = divmod(int(remaining.total_seconds()) // 60, 60)
            return f"Expires {exp_ist.strftime('%d %b %H:%M IST')}  ({h}h {m}m left)"
    except Exception:
        pass
    return "Token loaded"


# ──────────────────────────────────────────────────────────────────
# UpstoxAdapter
# ──────────────────────────────────────────────────────────────────

class UpstoxAdapter(CombinedBrokerAdapter):
    """
    Upstox v2 REST adapter (no SDK dependency — uses requests directly).

    Credentials (config.BROKER_CREDENTIALS["upstox"]):
      api_key      — from Upstox developer portal
      api_secret   — app secret
      redirect_uri — must match registered redirect URI (default: localhost:8888)
      access_token — filled after OAuth
    """

    def __init__(self):
        self._access_token:  Optional[str]      = None
        self._connected      = False
        self._creds          = config.BROKER_CREDENTIALS.get("upstox", {})
        self._session        = requests.Session()
        self._auth_url_cb:   Optional[Callable[[str], None]] = None
        self._pkce_verifier: Optional[str] = None

    # ── UI callback ───────────────────────────────────────────────
    def set_auth_url_callback(self, fn: Callable[[str], None]):
        self._auth_url_cb = fn

    def needs_auth(self) -> bool:
        return _load_upstox_token() is None

    def token_expiry_display(self) -> str:
        return upstox_token_expiry_display()

    # ── Step 1: Auth URL (PKCE) ───────────────────────────────────
    def generate_auth_url(self) -> str:
        """
        Generate Upstox OAuth URL using PKCE.
        Saves the code_verifier so exchange_auth_code() can use it.
        """
        self._creds     = config.BROKER_CREDENTIALS.get("upstox", {})
        api_key         = self._creds.get("api_key", "")
        redirect_uri    = self._creds.get("redirect_uri", REDIRECT_URI)

        # PKCE: code_verifier → code_challenge (S256)
        verifier        = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge_bytes = hashlib.sha256(verifier.encode()).digest()
        challenge       = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()
        self._pkce_verifier = verifier

        url = (
            f"https://api.upstox.com/v2/login/authorization/dialog"
            f"?response_type=code"
            f"&client_id={api_key}"
            f"&redirect_uri={redirect_uri}"
            f"&state=upstox_auth"
            f"&code_challenge={challenge}"
            f"&code_challenge_method=S256"
        )
        logger.info("Upstox auth URL generated")
        if self._auth_url_cb:
            self._auth_url_cb(url)
        return url

    # ── Step 2: Exchange auth code ────────────────────────────────
    def exchange_auth_code(self, auth_code: str) -> bool:
        self._creds      = config.BROKER_CREDENTIALS.get("upstox", {})
        api_key          = self._creds.get("api_key", "")
        api_secret       = self._creds.get("api_secret", "")
        redirect_uri     = self._creds.get("redirect_uri", REDIRECT_URI)
        verifier         = self._pkce_verifier or ""

        try:
            resp = requests.post(
                f"{UPSTOX_API}/login/authorization/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "code":          auth_code,
                    "client_id":     api_key,
                    "client_secret": api_secret,
                    "redirect_uri":  redirect_uri,
                    "grant_type":    "authorization_code",
                    "code_verifier": verifier,
                },
                timeout=15,
            )
            resp.raise_for_status()
            token = resp.json().get("access_token", "")
            if not token:
                logger.error(f"Upstox token exchange failed: {resp.text}")
                return False
            _save_upstox_token(token)
            return self._init_session(token)
        except Exception as e:
            logger.error(f"Upstox exchange error: {e}")
            return False

    # ── Step 2b: Direct token paste ───────────────────────────────
    def set_token_direct(self, token: str) -> bool:
        _save_upstox_token(token)
        return self._init_session(token)

    # ── Session ───────────────────────────────────────────────────
    def _init_session(self, access_token: str) -> bool:
        self._access_token = access_token
        self._session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/json",
        })
        try:
            resp = self._session.get(
                f"{UPSTOX_API}/user/profile", timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            logger.info(f"Upstox active — {data.get('user_name', '')}")
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Upstox session error: {e}")
            return False

    # ── CombinedBrokerAdapter interface ───────────────────────────

    def connect(self) -> bool:
        self._creds = config.BROKER_CREDENTIALS.get("upstox", {})
        cached = _load_upstox_token()
        if cached:
            return self._init_session(cached["access_token"])
        token = self._creds.get("access_token", "")
        if token:
            ok = self._init_session(token)
            if ok:
                _save_upstox_token(token)
            return ok
        logger.info("Upstox: auth required — call generate_auth_url()")
        return False

    def disconnect(self):
        self._connected    = False
        self._access_token = None
        self._session.headers.pop("Authorization", None)

    def is_connected(self) -> bool:
        return self._connected

    # ── Market Data ───────────────────────────────────────────────

    def get_spot_price(self, index_name: str) -> float:
        key = _INSTRUMENT_KEYS[index_name]
        try:
            resp = self._session.get(
                f"{UPSTOX_API}/market-quote/ltp",
                params={"instrument_key": key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            # Key in response uses pipe encoded as %7C or literal
            # Try both forms
            for k, v in data.items():
                if "last_price" in v:
                    return float(v["last_price"])
            return 0.0
        except Exception as e:
            logger.error(f"Upstox spot [{index_name}]: {e}")
            return 0.0

    def get_historical_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        key      = _INSTRUMENT_KEYS[index_name]
        interval = _INTERVAL_MAP.get(interval_minutes, "3minute")
        to_date  = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        # URL-encode the instrument key
        import urllib.parse
        key_encoded = urllib.parse.quote(key, safe="")

        try:
            resp = self._session.get(
                f"{UPSTOX_API}/historical-candle/{key_encoded}/{interval}/{to_date}/{from_date}",
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json().get("data", {}).get("candles", [])
            # Format: [timestamp, open, high, low, close, volume, oi]
            candles = []
            for r in raw:
                ts = datetime.fromisoformat(r[0]) if isinstance(r[0], str) else r[0]
                candles.append(Candle(
                    index_name=index_name,
                    timestamp=ts,
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]) if len(r) > 5 else 0.0,
                    interval=interval_minutes,
                ))
            # Upstox returns newest-first; reverse to oldest-first
            candles.reverse()
            return candles[-count:]
        except Exception as e:
            logger.error(f"Upstox candles [{index_name}]: {e}")
            return []

    # ── Options Data ──────────────────────────────────────────────

    def get_option_chain(self, index_name: str) -> OptionChain:
        """
        Fetch full option chain via Upstox v2 option chain endpoint.
        Automatically picks the nearest weekly expiry.
        """
        spot = self.get_spot_price(index_name)
        if spot == 0.0:
            return OptionChain(index_name, spot, "", [])

        gap = config.SYMBOL_MAP[index_name]["strike_gap"]
        atm = round(spot / gap) * gap
        key = _OPTION_CHAIN_KEYS[index_name]

        try:
            # Step 1: get available expiry dates
            resp = self._session.get(
                f"{UPSTOX_API}/option/contract",
                params={"instrument_key": key},
                timeout=10,
            )
            resp.raise_for_status()
            expiry_list = resp.json().get("data", [])
            if not expiry_list:
                return OptionChain(index_name, spot, "", [])

            # Nearest expiry (they come sorted ascending)
            nearest_expiry = expiry_list[0] if isinstance(expiry_list[0], str) \
                else expiry_list[0].get("expiry", "")

            # Step 2: fetch chain for that expiry
            resp2 = self._session.get(
                f"{UPSTOX_API}/option/chain",
                params={
                    "instrument_key": key,
                    "expiry_date":    nearest_expiry,
                },
                timeout=15,
            )
            resp2.raise_for_status()
            chain_data = resp2.json().get("data", [])

            # Step 3: build OptionStrike list
            strike_range = config.ATM_STRIKE_RANGE * gap
            strikes = []
            for item in chain_data:
                s = float(item.get("strike_price", 0))
                if abs(s - atm) > strike_range:
                    continue

                ce = item.get("call_options", {}).get("market_data", {})
                pe = item.get("put_options",  {}).get("market_data", {})
                ce_greeks = item.get("call_options", {}).get("option_greeks", {})
                pe_greeks = item.get("put_options",  {}).get("option_greeks", {})

                strikes.append(OptionStrike(
                    strike=s,
                    expiry=nearest_expiry,
                    call_oi=float(ce.get("oi", 0)),
                    call_oi_change=float(ce.get("change_oi", 0)),
                    call_volume=float(ce.get("volume", 0)),
                    call_iv=float(ce_greeks.get("iv", 0.0)),
                    call_ltp=float(ce.get("ltp", 0.0)),
                    put_oi=float(pe.get("oi", 0)),
                    put_oi_change=float(pe.get("change_oi", 0)),
                    put_volume=float(pe.get("volume", 0)),
                    put_iv=float(pe_greeks.get("iv", 0.0)),
                    put_ltp=float(pe.get("ltp", 0.0)),
                ))

            return OptionChain(index_name, spot, nearest_expiry, strikes)

        except Exception as e:
            logger.error(f"Upstox option chain [{index_name}]: {e}")
            return OptionChain(index_name, spot, "", [])
