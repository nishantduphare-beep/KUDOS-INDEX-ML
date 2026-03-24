"""
data/adapters/mock_adapter.py
─────────────────────────────────────────────────────────────────
Realistic mock adapter for development and testing.
Does not call any external API.

Simulates:
  • Realistic intraday price paths with occasional compression phases
  • Option chain with typical OI distribution and realistic PCR
  • Volume spikes during compression/accumulation phases
"""

import random
from datetime import datetime, timedelta, date
from typing import List, Dict
import math

import config
from data.base_api import CombinedBrokerAdapter
from data.structures import Candle, OptionChain, OptionStrike


class MockAdapter(CombinedBrokerAdapter):
    """
    Self-contained mock with realistic market simulation.
    Good for developing/testing without any broker connection.
    """

    # Approximate realistic base OI per index (in contracts)
    MOCK_BASE_OI = {
        "NIFTY":      8_500_000.0,
        "BANKNIFTY":  4_200_000.0,
        "MIDCPNIFTY": 1_100_000.0,
        "SENSEX":     2_800_000.0,
    }

    def __init__(self):
        self._prices: Dict[str, float] = dict(config.MOCK_BASE_PRICES)
        self._oi:     Dict[str, float] = dict(self.MOCK_BASE_OI)
        self._connected   = False
        self._candle_cache: Dict[str, List[Candle]] = {}
        self._tick        = 0

    # ─── Connection ───────────────────────────────────────────────

    def connect(self) -> bool:
        self._connected = True
        for idx in config.INDICES:
            self._candle_cache[idx] = self._generate_history(idx, 80)
        return True

    def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ─── Market Data ─────────────────────────────────────────────

    def get_spot_price(self, index_name: str) -> float:
        self._evolve_price(index_name)
        return round(self._prices[index_name], 2)

    def get_historical_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        self._append_candle(index_name)
        return self._candle_cache[index_name][-count:]

    # ─── Options Data ─────────────────────────────────────────────

    def get_option_chain(self, index_name: str) -> OptionChain:
        spot = self.get_spot_price(index_name)
        gap  = config.SYMBOL_MAP[index_name]["strike_gap"]
        atm  = round(spot / gap) * gap
        exp  = self._nearest_expiry()

        strikes: List[OptionStrike] = []
        for i in range(-10, 11):
            strike  = atm + i * gap
            dist    = abs(i)

            # OI peaks at ATM, decays outward — realistic shape
            oi_base   = 600_000 * math.exp(-0.15 * dist)
            call_oi   = int(max(500, oi_base * (0.8 + random.random() * 0.4)))
            put_oi    = int(max(500, oi_base * (0.9 + random.random() * 0.4)))

            # OI changes — small random deltas each cycle
            call_change = random.randint(-25_000, 25_000)
            put_change  = random.randint(-25_000, 25_000)

            # IV smile
            iv = 14.0 + dist * 0.6 + random.uniform(-0.5, 0.5)

            # LTP approximation
            call_ltp = max(0.5, (spot - strike) + iv * spot * 0.01 / 10) if i <= 0 else max(0.5, iv * spot * 0.01 / (dist + 1))
            put_ltp  = max(0.5, (strike - spot) + iv * spot * 0.01 / 10) if i >= 0 else max(0.5, iv * spot * 0.01 / (dist + 1))

            strikes.append(OptionStrike(
                strike=strike, expiry=exp,
                call_oi=call_oi, call_oi_change=call_change,
                call_volume=random.randint(500, 60_000),
                call_iv=round(iv, 2), call_ltp=round(call_ltp, 2),
                put_oi=put_oi, put_oi_change=put_change,
                put_volume=random.randint(500, 60_000),
                put_iv=round(iv, 2), put_ltp=round(put_ltp, 2),
            ))

        return OptionChain(index_name, spot, exp, strikes)

    def get_prev_day_close(self, index_name: str) -> float:
        """Mock: return a price slightly below the current simulated price."""
        base  = config.MOCK_BASE_PRICES.get(index_name, 0.0)
        vol   = config.MOCK_VOLATILITY.get(index_name, 0.001)
        return round(base * (1 - vol * 10), 2)

    def get_futures_candles(
        self,
        index_name:       str,
        interval_minutes: int = 3,
        count:            int = 60,
    ) -> List[Candle]:
        """Mock: realistic futures volume + slowly evolving open interest."""
        spot_candles = self.get_historical_candles(index_name, interval_minutes, count)
        base_oi  = self.MOCK_BASE_OI.get(index_name, 5_000_000.0)
        # Generate OI that drifts gradually (realistic accumulation/unwinding)
        oi = base_oi * random.uniform(0.92, 1.08)
        futures = []
        for c in spot_candles:
            oi += random.gauss(0, base_oi * 0.002)   # small drift per candle
            oi  = max(base_oi * 0.5, oi)              # floor at 50% of base
            fut_vol = float(int(abs(random.gauss(500_000, 150_000))))
            futures.append(Candle(
                c.index_name, c.timestamp,
                c.open, c.high, c.low, c.close,
                fut_vol, interval_minutes, oi=round(oi, 0)
            ))
        return futures

    # ─── Internal helpers ─────────────────────────────────────────

    def _evolve_price(self, index_name: str):
        vol = config.MOCK_VOLATILITY[index_name]
        drift = random.gauss(0, vol)
        # Occasional trending push
        if self._tick % 20 < 3:
            drift += vol * random.choice([-3, 3])
        self._prices[index_name] = max(
            self._prices[index_name] * (1 + drift),
            100.0
        )

    def _append_candle(self, index_name: str):
        cache = self._candle_cache.get(index_name, [])
        last  = cache[-1] if cache else None
        base  = last.close if last else self._prices[index_name]
        vol   = config.MOCK_VOLATILITY[index_name] * base

        # Inject compression phases
        in_compression = (self._tick % 35) < 6
        if in_compression:
            # Tight body, higher volume = stealth accumulation
            range_mult = 0.25
            vol_mult   = 2.2
        else:
            range_mult = 1.0
            vol_mult   = 1.0

        o = round(base + random.gauss(0, vol * 0.2 * range_mult), 2)
        c = round(o    + random.gauss(0, vol * range_mult), 2)
        h = round(max(o, c) + abs(random.gauss(0, vol * 0.3 * range_mult)), 2)
        l = round(min(o, c) - abs(random.gauss(0, vol * 0.3 * range_mult)), 2)
        v = int(abs(random.gauss(180_000, 60_000)) * vol_mult)

        self._tick += 1
        now = datetime.now().replace(second=0, microsecond=0)
        cache.append(Candle(index_name, now, o, h, l, c, float(v)))
        self._prices[index_name] = c

        if len(cache) > 200:
            cache.pop(0)
        self._candle_cache[index_name] = cache

    def _generate_history(self, index_name: str, count: int) -> List[Candle]:
        candles: List[Candle] = []
        price   = config.MOCK_BASE_PRICES[index_name]
        vol     = config.MOCK_VOLATILITY[index_name] * price
        t0      = datetime.now() - timedelta(minutes=3 * count)
        for i in range(count):
            o = round(price + random.gauss(0, vol * 0.2), 2)
            c = round(o + random.gauss(0, vol), 2)
            h = round(max(o, c) + abs(random.gauss(0, vol * 0.3)), 2)
            l = round(min(o, c) - abs(random.gauss(0, vol * 0.3)), 2)
            v = float(int(abs(random.gauss(180_000, 55_000))))
            candles.append(Candle(index_name, t0 + timedelta(minutes=3*i), o, h, l, c, v))
            price = c
        return candles

    @staticmethod
    def _nearest_expiry() -> str:
        today = date.today()
        # NSE weekly expiry = Thursday
        days  = (3 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days)).strftime("%d%b%Y").upper()
