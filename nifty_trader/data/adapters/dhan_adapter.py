"""
data/adapters/dhan_adapter.py
─────────────────────────────────────────────────────────────────
Dhan HQ API adapter.
Install: pip install dhanhq

Credentials (config.py → BROKER_CREDENTIALS["dhan"]):
  client_id    — Dhan client ID
  access_token — Dhan access token (from Dhan console)

Dhan does NOT use OAuth — credentials are long-lived API tokens
generated from https://dhanhq.co → My Profile → API Access.
"""

import logging
from datetime import datetime, timedelta
from typing import List

import config
from data.base_api import CombinedBrokerAdapter
from data.structures import Candle, OptionChain, OptionStrike

logger = logging.getLogger(__name__)

# Dhan security IDs for indices
_DHAN_SECURITY_IDS = {
    "NIFTY":     "13",
    "BANKNIFTY": "25",
    "MIDCPNIFTY":"27",
}


class DhanAdapter(CombinedBrokerAdapter):

    def __init__(self):
        self._dhan      = None
        self._connected = False
        self._creds     = config.BROKER_CREDENTIALS.get("dhan", {})

    def connect(self) -> bool:
        try:
            from dhanhq import dhanhq  # type: ignore
            self._dhan = dhanhq(self._creds["client_id"], self._creds["access_token"])
            # Quick verify
            profile = self._dhan.get_fund_limits()
            if profile.get("status") == "success":
                self._connected = True
                logger.info("Dhan connected")
                return True
            logger.error(f"Dhan auth failed: {profile}")
            return False
        except Exception as e:
            logger.error(f"Dhan connect error: {e}")
            return False

    def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ─── Market Data ─────────────────────────────────────────────

    def get_spot_price(self, index_name: str) -> float:
        sec_id = _DHAN_SECURITY_IDS[index_name]
        try:
            data = self._dhan.get_ltp("NSE", sec_id, "INDEX")
            return float(data["data"]["last_price"])
        except Exception as e:
            logger.error(f"Dhan spot [{index_name}]: {e}")
            return 0.0

    def get_historical_candles(self, index_name, interval_minutes=3, count=60):
        sec_id  = _DHAN_SECURITY_IDS[index_name]
        from_dt = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        to_dt   = datetime.now().strftime("%Y-%m-%d")
        try:
            data = self._dhan.historical_minute_charts(
                security_id=sec_id, exchange_segment="IDX_I",
                instrument_type="INDEX", expiry_code=0,
                from_date=from_dt, to_date=to_dt,
            )
            candles = [
                Candle(
                    index_name=index_name,
                    timestamp=datetime.strptime(r["start_Time"], "%Y-%m-%d %H:%M:%S"),
                    open=r["open"], high=r["high"],
                    low=r["low"],  close=r["close"],
                    volume=r.get("volume", 0),
                    interval=interval_minutes,
                )
                for r in data.get("data", [])
            ]
            # Group into N-minute candles if broker returns 1-min data
            return candles[-count:]
        except Exception as e:
            logger.error(f"Dhan candles [{index_name}]: {e}")
            return []

    # ─── Options Data ─────────────────────────────────────────────

    def get_option_chain(self, index_name: str) -> OptionChain:
        sec_id = _DHAN_SECURITY_IDS[index_name]
        spot   = self.get_spot_price(index_name)
        gap    = config.SYMBOL_MAP[index_name]["strike_gap"]
        atm    = round(spot / gap) * gap
        try:
            data   = self._dhan.option_chain(
                UnderlyingScrip=sec_id, UnderlyingSeg="IDX_I", Expirycode=1
            )
            oc_data = data.get("data", {})
            oc_raw  = oc_data.get("oc", [])

            # Update lot size from broker response if Dhan provides it.
            broker_lot = oc_data.get("lot_size") or oc_data.get("lotSize")
            if broker_lot and int(broker_lot) > 0:
                current = config.SYMBOL_MAP.get(index_name, {}).get("lot_size", 0)
                if current != int(broker_lot):
                    config.SYMBOL_MAP.setdefault(index_name, {})["lot_size"] = int(broker_lot)
                    logger.info(f"Lot size updated from broker [{index_name}]: {current} → {broker_lot}")
            strikes = []
            for item in oc_raw:
                s = float(item.get("strike_price", 0))
                if abs(s - atm) > config.ATM_STRIKE_RANGE * gap:
                    continue
                strikes.append(OptionStrike(
                    strike=s,
                    expiry=str(item.get("expiry_date", "")),
                    call_oi=float(item.get("ce", {}).get("oi", 0)),
                    call_oi_change=float(item.get("ce", {}).get("change_oi", 0)),
                    call_volume=float(item.get("ce", {}).get("volume", 0)),
                    call_iv=float(item.get("ce", {}).get("impl_volatility", 0)),
                    call_ltp=float(item.get("ce", {}).get("last_price", 0)),
                    put_oi=float(item.get("pe", {}).get("oi", 0)),
                    put_oi_change=float(item.get("pe", {}).get("change_oi", 0)),
                    put_volume=float(item.get("pe", {}).get("volume", 0)),
                    put_iv=float(item.get("pe", {}).get("impl_volatility", 0)),
                    put_ltp=float(item.get("pe", {}).get("last_price", 0)),
                ))
            expiry = oc_raw[0].get("expiry_date", "") if oc_raw else ""
            return OptionChain(index_name, spot, str(expiry), strikes)
        except Exception as e:
            logger.error(f"Dhan option chain [{index_name}]: {e}")
            return OptionChain(index_name, spot, "", [])
