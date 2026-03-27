"""
data/adapters/fyers_adapter.py
─────────────────────────────────────────────────────────────────
Fyers API v3 adapter — full OAuth2 + token lifecycle management.

Redirect URI:  https://trade.fyers.in/api-login/redirect-uri/index.html

Credentials:
    Client ID   — e.g. "XB12345"
    App ID      — e.g. "XB12345-100"  (Client ID + "-100")
    Secret Key  — app secret

Auth flow:
  1. generate_auth_url() → open browser → user logs in
  2. Fyers redirects to redirect_uri with ?auth_code=XXXX in URL
  3. exchange_auth_code(code) → save access_token to disk
  4. Token valid until midnight IST same day
  5. Next launch: auto-load if not expired, else prompt for new code

Install:  pip install fyers-apiv3
"""

import json
import logging
import math
import os
from calendar import monthrange
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import List, Optional, Callable, Dict

import config
from data.base_api import CombinedBrokerAdapter
from data.structures import Candle, OptionChain, OptionStrike

# ──────────────────────────────────────────────────────────────────
# Black-Scholes IV computation (Fyers v3 doesn't return IV in chain)
# ──────────────────────────────────────────────────────────────────

def _bs_iv(ltp: float, spot: float, strike: float,
           tte: float, rate: float, opt_type: str) -> float:
    """
    Compute implied volatility via Black-Scholes + Brent root-finding.
    Returns IV as a percentage (e.g. 18.5 means 18.5%).
    Returns 0.0 when IV cannot be determined.

    ltp      — option market price
    spot     — underlying spot price
    strike   — option strike
    tte      — time to expiry in years (e.g. 0.0274 for 10 days)
    rate     — risk-free rate (e.g. 0.065 for 6.5%)
    opt_type — "CE" or "PE"
    """
    if ltp <= 0 or spot <= 0 or strike <= 0 or tte <= 0:
        return 0.0
    try:
        from scipy.stats import norm
        from scipy.optimize import brentq

        def bs(sigma: float) -> float:
            if sigma <= 1e-6:
                return 0.0
            d1 = (math.log(spot / strike) + (rate + 0.5 * sigma ** 2) * tte) / (sigma * math.sqrt(tte))
            d2 = d1 - sigma * math.sqrt(tte)
            if opt_type == "CE":
                return spot * norm.cdf(d1) - strike * math.exp(-rate * tte) * norm.cdf(d2)
            else:
                return strike * math.exp(-rate * tte) * norm.cdf(-d2) - spot * norm.cdf(-d1)

        # Intrinsic value check — LTP below intrinsic means bad data, skip
        intrinsic = (max(0.0, spot - strike) if opt_type == "CE"
                     else max(0.0, strike - spot))
        if ltp < intrinsic * 0.99:
            return 0.0

        iv = brentq(lambda s: bs(s) - ltp, 1e-4, 20.0, maxiter=100, xtol=1e-4)
        return round(iv * 100.0, 2)   # express as percentage
    except Exception:
        return 0.0

logger = logging.getLogger(__name__)

TOKEN_FILE = Path("auth/fyers_token.json")
_IST = config.IST
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"


# ──────────────────────────────────────────────────────────────────
# Token persistence helpers
# ──────────────────────────────────────────────────────────────────

def _midnight_ist_utc() -> datetime:
    """Next midnight IST expressed as UTC (Fyers token expiry)."""
    now_ist = datetime.now(_IST)
    midnight = (now_ist + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def save_fyers_token(access_token: str, app_id: str):
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    exp = _midnight_ist_utc()
    payload = {
        "access_token": access_token,
        "app_id":       app_id,
        "saved_at":     datetime.utcnow().isoformat(),
        "expires_at":   exp.isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    config.BROKER_CREDENTIALS["fyers"]["access_token"] = access_token
    config.BROKER_CREDENTIALS["fyers"]["token_expiry"] = exp.isoformat()
    logger.info(f"Fyers token saved — expires {exp.strftime('%d %b %Y %H:%M UTC')}")


def load_fyers_token() -> Optional[Dict]:
    """Returns cached token dict if valid, else None."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        exp  = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        remaining = exp - datetime.now(timezone.utc)
        if remaining.total_seconds() > 300:          # > 5 minutes left
            h, m = divmod(int(remaining.total_seconds()) // 60, 60)
            logger.debug(f"Fyers token valid — {h}h {m}m remaining")
            return data
        logger.info("Fyers token expired")
    except Exception as e:
        logger.warning(f"Token read error: {e}")
    return None


def fyers_token_expiry_display() -> str:
    """Human-readable expiry string for UI."""
    data = load_fyers_token()
    if not data:
        return "No valid token"
    try:
        exp = datetime.fromisoformat(data["expires_at"])
        if exp.tzinfo:
            exp_ist = exp.astimezone(_IST)
            remaining = exp - datetime.now(timezone.utc)
            h, m = divmod(int(remaining.total_seconds()) // 60, 60)
            return f"Expires {exp_ist.strftime('%d %b %H:%M IST')}  ({h}h {m}m left)"
    except Exception:
        pass
    return "Token loaded"


# ──────────────────────────────────────────────────────────────────
# Fyers Adapter
# ──────────────────────────────────────────────────────────────────

class FyersAdapter(CombinedBrokerAdapter):

    SPOT_SYMBOLS = {
        "NIFTY":      "NSE:NIFTY50-INDEX",
        "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
        "SENSEX":     "BSE:SENSEX-INDEX",
    }
    INTERVAL_MAP = {1:"1", 3:"3", 5:"5", 10:"10", 15:"15", 30:"30", 60:"60"}

    def __init__(self):
        self._fyers     = None
        self._connected = False
        self._creds     = config.BROKER_CREDENTIALS.get("fyers", {})
        self._auth_url_cb: Optional[Callable[[str], None]] = None
        # Spot price cache — reused within TTL to avoid rate limiting
        self._spot_cache: dict = {}
        self._spot_cache_ts: float = 0.0
        self._SPOT_CACHE_TTL: float = 8.0   # seconds — covers one 5s tick cycle with margin

    # ─── UI callback ─────────────────────────────────────────────
    def set_auth_url_callback(self, fn: Callable[[str], None]):
        self._auth_url_cb = fn

    # ─── Token state ─────────────────────────────────────────────
    def needs_auth(self) -> bool:
        return load_fyers_token() is None

    def token_expiry_display(self) -> str:
        return fyers_token_expiry_display()

    # ─── Step 1: Auth URL ─────────────────────────────────────────
    def generate_auth_url(self) -> str:
        self._creds = config.BROKER_CREDENTIALS.get("fyers", {})
        app_id  = self._creds.get("app_id", "")
        secret  = self._creds.get("secret_key", "")
        redir   = self._creds.get("redirect_uri", REDIRECT_URI)
        try:
            from fyers_apiv3.fyersModel import SessionModel  # type: ignore
            sess = SessionModel(
                client_id=app_id, secret_key=secret,
                redirect_uri=redir, response_type="code",
                grant_type="authorization_code",
            )
            url = sess.generate_authcode()
            logger.info("Fyers auth URL generated")
            if self._auth_url_cb:
                self._auth_url_cb(url)
            return url
        except ImportError:
            raise ImportError("Run: pip install fyers-apiv3")

    # ─── Step 2: Exchange code ────────────────────────────────────
    def exchange_auth_code(self, auth_code: str) -> bool:
        self._creds = config.BROKER_CREDENTIALS.get("fyers", {})
        app_id  = self._creds.get("app_id", "")
        secret  = self._creds.get("secret_key", "")
        redir   = self._creds.get("redirect_uri", REDIRECT_URI)
        try:
            from fyers_apiv3.fyersModel import SessionModel  # type: ignore
            sess = SessionModel(
                client_id=app_id, secret_key=secret,
                redirect_uri=redir, response_type="code",
                grant_type="authorization_code",
            )
            sess.set_token(auth_code)
            resp = sess.generate_token()
            if resp.get("s") == "ok":
                token = resp["access_token"]
                save_fyers_token(token, app_id)
                return self._init_session(app_id, token)
            logger.error(f"Exchange failed: {resp}")
            return False
        except Exception as e:
            logger.error(f"Exchange error: {e}")
            return False

    # ─── Step 2b: Direct token paste ─────────────────────────────
    def set_token_direct(self, token: str) -> bool:
        """User pastes token text directly."""
        self._creds = config.BROKER_CREDENTIALS.get("fyers", {})
        app_id = self._creds.get("app_id", "")
        save_fyers_token(token, app_id)
        return self._init_session(app_id, token)

    # ─── Session ─────────────────────────────────────────────────
    def _init_session(self, app_id: str, token: str) -> bool:
        try:
            from fyers_apiv3.fyersModel import FyersModel  # type: ignore
            os.makedirs("logs/fyers", exist_ok=True)
            self._fyers = FyersModel(
                client_id=app_id,
                token=token,
                log_path="logs/fyers",
            )
            profile = self._fyers.get_profile()
            if profile.get("s") == "ok":
                name = profile.get("data", {}).get("name", "")
                logger.info(f"Fyers active — {name}")
                self._connected = True
                return True
            logger.error(f"Profile check: {profile}")
            return False
        except Exception as e:
            logger.error(f"Fyers session error: {e}")
            return False

    # ─── CombinedBrokerAdapter interface ─────────────────────────
    def connect(self) -> bool:
        self._creds = config.BROKER_CREDENTIALS.get("fyers", {})
        # Try cached token first
        cached = load_fyers_token()
        if cached:
            return self._init_session(
                cached.get("app_id", self._creds.get("app_id", "")),
                cached["access_token"]
            )
        # Try token from config
        token  = self._creds.get("access_token", "")
        app_id = self._creds.get("app_id", "")
        if token and app_id:
            ok = self._init_session(app_id, token)
            if ok:
                save_fyers_token(token, app_id)
            return ok
        logger.info("Fyers: auth required")
        return False

    def disconnect(self):
        self._connected = False
        self._fyers = None

    def is_connected(self) -> bool:
        return self._connected

    # ─── Market Data ─────────────────────────────────────────────
    def get_all_spot_prices(self) -> dict:
        """
        Fetch all index spot prices in ONE API call to avoid rate limiting.
        Returns {index_name: price} for all indices in SPOT_SYMBOLS.
        Results are cached for _SPOT_CACHE_TTL seconds to prevent burst API calls.
        Timestamp is always updated (even on failure) so 429s don't trigger rapid retries.
        """
        if not self._fyers:
            return {}
        import time
        now = time.time()
        # Return cached value if still within TTL — regardless of whether cache is populated
        if (now - self._spot_cache_ts) < self._SPOT_CACHE_TTL:
            return dict(self._spot_cache)
        try:
            symbols = ",".join(self.SPOT_SYMBOLS.values())
            # Claim the slot BEFORE the API call (optimistic lock).
            # Any concurrent thread will see TTL as fresh and return stale cache.
            self._spot_cache_ts = time.time()
            resp = self._fyers.quotes({"symbols": symbols})
            if resp is None:
                return dict(self._spot_cache)
            d = resp.get("d", [])
            if not d:
                logger.warning(f"Fyers batch quotes empty: {resp}")
                return dict(self._spot_cache)
            # Build reverse map: symbol → index_name
            rev = {v: k for k, v in self.SPOT_SYMBOLS.items()}
            result = {}
            for item in d:
                sym = item.get("n", "")
                lp  = item.get("v", {}).get("lp", 0)
                idx = rev.get(sym)
                if idx and lp:
                    result[idx] = float(lp)
            if result:
                self._spot_cache = result
            return dict(self._spot_cache)
        except Exception as e:
            logger.error(f"Fyers batch quotes: {e}")
            self._spot_cache_ts = time.time()  # prevent rapid retry on exception too
            return dict(self._spot_cache)

    def get_spot_price(self, index_name: str) -> float:
        """Single-index spot — prefer get_all_spot_prices() to avoid rate limiting."""
        prices = self.get_all_spot_prices()
        return prices.get(index_name, 0.0)

    def get_historical_candles(self, index_name: str, interval_minutes: int = 3, count: int = 60) -> List[Candle]:
        if not self._fyers:
            return []
        from_dt = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            resp = self._fyers.history({
                "symbol": self.SPOT_SYMBOLS[index_name],
                "resolution": self.INTERVAL_MAP.get(interval_minutes, "3"),
                "date_format": "1",
                "range_from": from_dt,
                "range_to": datetime.now().strftime("%Y-%m-%d"),
                "cont_flag": "1",
            })
            candles = [
                Candle(index_name, datetime.fromtimestamp(r[0]),
                       float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                       float(r[5]), interval_minutes)
                for r in resp.get("candles", [])
            ]
            return candles[-count:]
        except Exception as e:
            logger.error(f"Fyers candles [{index_name}]: {e}")
            return []

    # ─── Futures Volume ───────────────────────────────────────────
    @staticmethod
    def _near_month_futures_symbol(index_name: str) -> str:
        """
        Compute Fyers near-month futures symbol.
        NSE format: NSE:NIFTY25MARFUT  (last Thursday expiry)
        BSE format: BSE:SENSEX25MARFUT (last Friday expiry)
        Rolls to next month within 2 days of expiry.
        """
        today = date.today()

        # BSE SENSEX futures expire last Friday; all others last Thursday
        expiry_weekday = 4 if index_name == "SENSEX" else 3  # 4=Fri, 3=Thu

        def last_weekday(year, month, weekday):
            last_day = monthrange(year, month)[1]
            d = date(year, month, last_day)
            while d.weekday() != weekday:
                d -= timedelta(days=1)
            return d

        expiry = last_weekday(today.year, today.month, expiry_weekday)
        if (expiry - today).days <= 2:
            nxt_month = today.month + 1 if today.month < 12 else 1
            nxt_year  = today.year if today.month < 12 else today.year + 1
            expiry    = last_weekday(nxt_year, nxt_month, expiry_weekday)

        yr  = expiry.strftime("%y")          # "25"
        mon = expiry.strftime("%b").upper()  # "MAR"
        prefix = config.FUTURES_SYMBOL_PREFIX.get(index_name, f"NSE:{index_name}")
        return f"{prefix}{yr}{mon}FUT"

    def get_futures_candles(
        self, index_name: str, interval_minutes: int = 3, count: int = 60
    ) -> List[Candle]:
        """Fetch near-month futures candles for real volume data.
        Note: Fyers history API returns 6 elements [ts,o,h,l,c,vol] — no OI.
        OI is populated separately via get_all_futures_quotes().
        """
        if not self._fyers:
            return []
        symbol  = self._near_month_futures_symbol(index_name)
        from_dt = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            resp = self._fyers.history({
                "symbol":      symbol,
                "resolution":  self.INTERVAL_MAP.get(interval_minutes, "3"),
                "date_format": "1",
                "range_from":  from_dt,
                "range_to":    datetime.now().strftime("%Y-%m-%d"),
                "cont_flag":   "1",
            })
            candles = [
                Candle(index_name, datetime.fromtimestamp(r[0]),
                       float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                       float(r[5]), interval_minutes,
                       oi=0.0)   # OI not in history API; fetched via get_all_futures_quotes()
                for r in resp.get("candles", [])
            ]
            logger.debug(f"Futures candles [{index_name}] {symbol}: {len(candles)} bars")
            return candles[-count:]
        except Exception as e:
            logger.error(f"Fyers futures candles [{index_name}]: {e}")
            return []

    def get_all_futures_quotes(self) -> Dict[str, Dict]:
        """
        Batch-fetch real-time futures quotes for all indices in ONE API call.
        Returns {index_name: {"oi": float, "lp": float}} for each index.
        Fyers quotes() returns OI in v.oi for futures symbols.
        """
        if not self._fyers:
            return {}
        symbols_map: Dict[str, str] = {
            idx: self._near_month_futures_symbol(idx)
            for idx in config.INDICES
        }
        try:
            symbols_str = ",".join(symbols_map.values())
            logger.debug(f"Futures quotes request: {symbols_str}")
            resp = self._fyers.quotes({"symbols": symbols_str})
            if not resp or resp.get("s") != "ok":
                logger.warning(f"Futures quotes API error: {resp}")
                return {}
            d = resp.get("d", [])
            # Build reverse map: fyers_symbol → index_name (exact match)
            rev = {v: k for k, v in symbols_map.items()}
            # Also build suffix-only fallback: bare symbol (no exchange prefix) → index_name
            # e.g. "NIFTY26MARFUT" → "NIFTY" in case Fyers drops the exchange prefix
            rev_bare = {v.split(":", 1)[-1]: k for k, v in symbols_map.items()}
            result: Dict[str, Dict] = {}
            returned_syms = [item.get("n", "") for item in d]
            logger.debug(f"Futures quotes returned symbols: {returned_syms}")
            for item in d:
                sym = item.get("n", "")
                v   = item.get("v", {})
                # Exact match first, then bare fallback
                idx = rev.get(sym) or rev_bare.get(sym.split(":", 1)[-1])
                if idx:
                    oi_val = float(v.get("oi", 0) or 0)
                    lp_val = float(v.get("lp", 0) or 0)
                    result[idx] = {"oi": oi_val, "lp": lp_val}
                    logger.debug(f"Futures OI [{idx}] sym={sym} oi={oi_val} lp={lp_val}")
                else:
                    logger.warning(f"Futures quotes: unrecognised symbol '{sym}' "
                                   f"(expected one of {list(rev.keys())})")
            return result
        except Exception as e:
            logger.error(f"Fyers futures quotes: {e}")
            return {}

    # ─── India VIX ───────────────────────────────────────────────
    def get_vix(self) -> float:
        """
        Fetch India VIX from Fyers quotes API.
        Symbol: NSE:INDIA VIX — available as a Fyers index quote.
        Returns 0.0 on failure (VIX unavailable from all brokers).
        """
        if not self._fyers:
            return 0.0
        try:
            resp = self._fyers.quotes({"symbols": "NSE:INDIA VIX"})
            if resp and resp.get("s") == "ok":
                d = resp.get("d", [])
                if d:
                    vix = float(d[0].get("v", {}).get("lp", 0) or 0)
                    if vix > 0:
                        return vix
            # API returned ok but no usable VIX value
            logger.debug("VIX fetch: empty response from Fyers")
        except Exception as e:
            # m3 fix: warn once per session instead of silent debug
            if not getattr(self, "_vix_warn_logged", False):
                logger.warning(f"VIX fetch failed (will keep retrying silently): {e}")
                self._vix_warn_logged = True
        return 0.0

    # ─── Previous Day Close ───────────────────────────────────────
    def get_prev_day_close(self, index_name: str) -> float:
        """
        Fetch recent daily candles and return yesterday's close.

        Fyers does NOT include today's partial candle during market hours,
        so candles[-1] is always the last completed trading day (yesterday).
        We verify by checking the timestamp of the last candle:
          - If its date == today  → today's candle IS present → use candles[-2]
          - If its date <  today  → candles[-1] IS yesterday  → use candles[-1]
        This prevents the off-by-one bug where day-before-yesterday was returned.
        """
        if not self._fyers:
            return 0.0
        from_dt = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            resp = self._fyers.history({
                "symbol":      self.SPOT_SYMBOLS[index_name],
                "resolution":  "D",
                "date_format": "1",
                "range_from":  from_dt,
                "range_to":    datetime.now().strftime("%Y-%m-%d"),
                "cont_flag":   "1",
            })
            candles = resp.get("candles", [])
            if not candles:
                return 0.0

            # Determine whether today's candle is included
            last_ts   = candles[-1][0]          # Unix timestamp
            last_date = datetime.fromtimestamp(last_ts).date()
            today     = datetime.now().date()

            if last_date >= today:
                # Today's candle present → candles[-1] is today, candles[-2] is yesterday
                if len(candles) >= 2:
                    return float(candles[-2][4])
            else:
                # Today's candle not yet formed → candles[-1] IS yesterday
                return float(candles[-1][4])

        except Exception as e:
            logger.error(f"Fyers prev_day_close [{index_name}]: {e}")
        return 0.0

    # ─── Expiry Dates ─────────────────────────────────────────────
    def get_expiry_dates(self, index_name: str) -> List[str]:
        """
        Return all available expiry date strings from Fyers, nearest first.
        Format matches what Fyers returns in expiryData[].date  e.g. "19-Mar-2025".
        Falls back to empty list on any error.
        """
        if not self._fyers:
            return []
        try:
            resp = self._fyers.optionchain({
                "symbol":      self.SPOT_SYMBOLS[index_name],
                "strikecount": 1,   # minimal payload — we only need expiry list
                "timestamp":   "",
            })
            expiry_list = resp.get("data", {}).get("expiryData", [])
            return [e["date"] for e in expiry_list if "date" in e]
        except Exception as e:
            logger.debug(f"Fyers get_expiry_dates [{index_name}]: {e}")
            return []

    # ─── Options Data ─────────────────────────────────────────────
    def get_option_chain(self, index_name: str) -> OptionChain:
        """
        Fyers v3 optionchain response structure:
          resp["data"]["expiryData"]   → list of {date, expiry(unix)}
          resp["data"]["optionsChain"] → flat list of individual CE/PE items
            each item: {strike_price, option_type, oi, oich, volume, ltp, ...}
            index row has strike_price == -1 (skip it)
        """
        if not self._fyers:
            return OptionChain(index_name, 0.0, "", [])
        spot = self.get_spot_price(index_name)
        try:
            resp = self._fyers.optionchain({
                "symbol":      self.SPOT_SYMBOLS[index_name],
                "strikecount": config.ATM_STRIKE_RANGE,
                "timestamp":   "",
            })

            data        = resp.get("data", {})
            expiry_list = data.get("expiryData", [])
            expiry_str  = expiry_list[0].get("date", "") if expiry_list else ""
            raw_chain   = data.get("optionsChain", [])

            # Update lot size from broker response — Fyers returns lotSize in data dict.
            # This keeps config.SYMBOL_MAP current without any extra API call.
            broker_lot = (data.get("lotSize") or data.get("lot_size") or
                          (expiry_list[0].get("lotSize") if expiry_list else None))
            if broker_lot and int(broker_lot) > 0:
                current = config.SYMBOL_MAP.get(index_name, {}).get("lot_size", 0)
                if current != int(broker_lot):
                    config.SYMBOL_MAP.setdefault(index_name, {})["lot_size"] = int(broker_lot)
                    logger.info(f"Lot size updated from broker [{index_name}]: {current} → {broker_lot}")

            # Time-to-expiry — use Unix timestamp from broker (no parsing needed)
            expiry_unix = int(expiry_list[0].get("expiry", 0)) if expiry_list else 0
            if expiry_unix:
                from datetime import timezone as _tz
                _exp_date = datetime.fromtimestamp(expiry_unix, tz=_tz.utc).date()
                _days     = max(0, (_exp_date - date.today()).days)
                tte       = max(0.0001, _days / 365.0)
            else:
                tte = 0.0

            # Group flat CE/PE list into per-strike dict
            strike_map: Dict[float, Dict] = {}
            for item in raw_chain:
                s = float(item.get("strike_price", -1))
                if s < 0:           # skip the index spot row
                    continue
                opt_type = item.get("option_type", "")
                if opt_type not in ("CE", "PE"):
                    continue
                if s not in strike_map:
                    strike_map[s] = {}
                strike_map[s][opt_type] = {
                    "oi":        float(item.get("oi",     0)),
                    "oi_change": float(item.get("oich",   0)),
                    "volume":    float(item.get("volume", 0)),
                    "ltp":       float(item.get("ltp",    0)),
                }

            _rate = 0.065   # India risk-free rate (~repo rate)
            strikes = []
            for s_price in sorted(strike_map):
                d       = strike_map[s_price]
                ce      = d.get("CE", {})
                pe      = d.get("PE", {})
                ce_ltp  = ce.get("ltp", 0.0)
                pe_ltp  = pe.get("ltp", 0.0)
                call_iv = _bs_iv(ce_ltp, spot, s_price, tte, _rate, "CE")
                put_iv  = _bs_iv(pe_ltp, spot, s_price, tte, _rate, "PE")
                strikes.append(OptionStrike(
                    strike=s_price, expiry=expiry_str,
                    call_oi=ce.get("oi", 0),
                    call_oi_change=ce.get("oi_change", 0),
                    call_volume=ce.get("volume", 0),
                    call_iv=call_iv,
                    call_ltp=ce_ltp,
                    put_oi=pe.get("oi", 0),
                    put_oi_change=pe.get("oi_change", 0),
                    put_volume=pe.get("volume", 0),
                    put_iv=put_iv,
                    put_ltp=pe_ltp,
                ))

            return OptionChain(index_name, spot, expiry_str, strikes)
        except Exception as e:
            logger.error(f"Fyers option chain [{index_name}]: {e}")
            return OptionChain(index_name, spot, "", [])
