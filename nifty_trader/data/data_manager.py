"""
data/data_manager.py
─────────────────────────────────────────────────────────────────
Orchestrates live data fetching via the adapter registry.
Maintains per-index state (candles + option chain).
Runs two background threads: tick_thread (spot + OC) and candle_thread.

All callers (engines, UI) read from this manager only — they never
touch the adapter directly.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
from datetime import datetime as _dt_type  # alias to avoid shadowing

import pandas as pd
import numpy as np

import config
from data.structures import Candle, OptionChain
from data.base_api import CombinedBrokerAdapter
from data.adapters import get_adapter
from database.manager import get_db

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# INDEX STATE
# ──────────────────────────────────────────────────────────────────

class IndexState:
    """All current live state for one index."""

    def __init__(self, index_name: str):
        self.index_name    = index_name
        self.spot_price    = 0.0
        self.prev_day_close = 0.0
        self.candles: List[Candle] = []
        self.option_chain: Optional[OptionChain] = None
        self.df:           Optional[pd.DataFrame] = None
        self.df_5m:        Optional[pd.DataFrame] = None   # 5-min candles for MTF
        self.df_15m:       Optional[pd.DataFrame] = None   # 15-min candles for MTF
        self.futures_df:   Optional[pd.DataFrame] = None   # futures OHLCV + OI
        self.futures_price: float = 0.0
        self.last_updated: Optional[datetime] = None
        self._lock = threading.Lock()

        # Pre-opening snapshot (9:00–9:14 IST) — frozen at session start for all-day ML feature
        # Captures futures LTP + volume during NSE pre-open before spot trading begins.
        # Spot has no real volume in pre-open; futures DO have real buy/sell activity.
        self.preopen_gap_pct:    float = 0.0  # (futures_ltp_at_preopen - prev_close) / prev_close * 100
        self.preopen_futures_ltp: float = 0.0  # last captured futures LTP during pre-open
        self._preopen_locked:    bool  = False  # True once 9:15 AM passes

    def update_candles(self, candles: List[Candle],
                       futures_candles: Optional[List[Candle]] = None):
        with self._lock:
            if futures_candles and config.USE_FUTURES_VOLUME:
                candles = self._merge_futures_volume(candles, futures_candles)
            self.candles      = candles
            self.df           = self._build_dataframe(candles, max_rows=config.CANDLE_HISTORY_COUNT)
            self.last_updated = datetime.now()
            # Store futures DataFrame (separate from spot df — keeps OI)
            if futures_candles:
                rows = [{"timestamp": c.timestamp, "open": c.open, "high": c.high,
                         "low": c.low, "close": c.close, "volume": c.volume,
                         "oi": c.oi} for c in futures_candles]
                fdf = pd.DataFrame(rows)
                fdf["timestamp"] = pd.to_datetime(fdf["timestamp"])
                fdf = fdf.sort_values("timestamp").reset_index(drop=True)
                self.futures_df    = fdf
                self.futures_price = float(fdf.iloc[-1]["close"]) if len(fdf) > 0 else 0.0

    @staticmethod
    def _merge_futures_volume(
        spot: List[Candle], futures: List[Candle]
    ) -> List[Candle]:
        """Replace spot candle volume (and OI) with futures contract data (same timestamp)."""
        fut_vol: Dict[datetime, float] = {
            c.timestamp.replace(second=0, microsecond=0): c.volume
            for c in futures
        }
        fut_oi: Dict[datetime, float] = {
            c.timestamp.replace(second=0, microsecond=0): c.oi
            for c in futures
        }
        merged = []
        for c in spot:
            ts  = c.timestamp.replace(second=0, microsecond=0)
            vol = fut_vol.get(ts, c.volume)   # fallback to spot volume if no match
            oi  = fut_oi.get(ts, 0.0)
            merged.append(Candle(
                c.index_name, c.timestamp,
                c.open, c.high, c.low, c.close,
                vol, c.interval, oi=oi
            ))
        return merged

    def update_candles_5m(self, candles: List[Candle]):
        with self._lock:
            self.df_5m = self._build_dataframe(
                candles, max_rows=config.MTF_5M_HISTORY_COUNT
            ) if candles else None

    def update_candles_15m(self, candles: List[Candle]):
        with self._lock:
            self.df_15m = self._build_dataframe(
                candles, max_rows=config.MTF_15M_HISTORY_COUNT
            ) if candles else None

    def get_df_5m(self) -> Optional[pd.DataFrame]:
        with self._lock:
            return self.df_5m.copy() if self.df_5m is not None and len(self.df_5m) > 0 else None

    def get_df_15m(self) -> Optional[pd.DataFrame]:
        with self._lock:
            return self.df_15m.copy() if self.df_15m is not None and len(self.df_15m) > 0 else None

    def update_option_chain(self, chain: OptionChain):
        with self._lock:
            self.option_chain = chain

    def update_spot(self, price: float):
        with self._lock:
            if price and price > 0:   # never overwrite a good value with 0
                self.spot_price = price

    def get_df(self) -> Optional[pd.DataFrame]:
        with self._lock:
            return self.df.copy() if self.df is not None and len(self.df) > 0 else None

    def get_futures_df(self) -> Optional[pd.DataFrame]:
        with self._lock:
            return self.futures_df.copy() if self.futures_df is not None and len(self.futures_df) > 0 else None

    def update_preopen_futures_ltp(self, ltp: float):
        """Record latest futures LTP during pre-open window (9:00–9:14 IST). No-op after lock."""
        with self._lock:
            if not self._preopen_locked and ltp > 0:
                self.preopen_futures_ltp = ltp

    def lock_preopen_snapshot(self):
        """
        Freeze preopen_gap_pct at session start (9:15 AM).
        Must be called after prev_day_close is set.
        No-op if already locked or no futures LTP was captured.
        """
        with self._lock:
            if self._preopen_locked or self.preopen_futures_ltp <= 0:
                return
            prev = self.prev_day_close
            if prev > 0:
                self.preopen_gap_pct = (self.preopen_futures_ltp - prev) / prev * 100
            self._preopen_locked = True
            logger.debug(f"[{self.index_name}] Pre-open locked: "
                         f"futures_ltp={self.preopen_futures_ltp:.2f} "
                         f"prev_close={prev:.2f} gap={self.preopen_gap_pct:.3f}%")

    def update_futures_oi_tick(self, oi: float, lp: float = 0.0):
        """
        Patch the OI (and optionally lp/close) of the latest row in futures_df.
        Called every tick from DataManager to propagate real-time OI from quotes API.
        """
        with self._lock:
            if self.futures_df is None or len(self.futures_df) == 0:
                return
            self.futures_df.at[self.futures_df.index[-1], "oi"] = oi
            if lp and lp > 0:
                self.futures_df.at[self.futures_df.index[-1], "close"] = lp
                self.futures_price = lp

    def restore_oi_history(self, oi_rows: list):
        """
        Merge DB-persisted intraday OI rows into futures_df on startup.
        oi_rows: list of MarketCandle ORM objects with .timestamp and .oi.
        Matches by minute-truncated timestamp.
        """
        with self._lock:
            if self.futures_df is None or len(self.futures_df) == 0 or not oi_rows:
                return
            oi_map = {
                pd.Timestamp(r.timestamp).floor("min"): float(r.oi or 0)
                for r in oi_rows
                if r.oi and r.oi > 0
            }
            if not oi_map:
                return
            ts_series = pd.to_datetime(self.futures_df["timestamp"]).dt.floor("min")
            self.futures_df["oi"] = ts_series.map(oi_map).fillna(self.futures_df["oi"])
            logger.debug(f"[{self.index_name}] OI history restored: {len(oi_map)} rows")

    def get_option_chain(self) -> Optional[OptionChain]:
        with self._lock:
            return self.option_chain

    # ── Indicator computation ─────────────────────────────────────

    @staticmethod
    def _build_dataframe(candles: List[Candle], max_rows: int = 0) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame()
        rows = [c.to_dict() for c in candles]
        df   = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        # Cap size to prevent unbounded memory growth on intraday refetches
        if max_rows > 0 and len(df) > max_rows:
            df = df.iloc[-max_rows:].reset_index(drop=True)
        df = IndexState._add_indicators(df)
        return df

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 2:
            return df

        h, l, c = df["high"], df["low"], df["close"]

        # ── True Range / ATR ─────────────────────────────────────
        tr = pd.concat([
            h - l,
            (h - c.shift(1)).abs(),
            (l - c.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_p    = min(config.ATR_PERIOD, len(df) - 1)
        df["tr"] = tr
        df["atr"] = tr.ewm(span=atr_p, adjust=False).mean()

        # ── DI / ADX ─────────────────────────────────────────────
        up_move   = h - h.shift(1)
        down_move = l.shift(1) - l
        plus_dm   = np.where((up_move > down_move)   & (up_move   > 0), up_move,   0.0)
        minus_dm  = np.where((down_move > up_move)   & (down_move > 0), down_move, 0.0)

        adx_p     = min(config.ADX_PERIOD, len(df) - 1)
        atr_s     = tr.ewm(span=adx_p, adjust=False).mean()
        pdi_raw   = pd.Series(plus_dm).ewm(span=adx_p, adjust=False).mean()
        mdi_raw   = pd.Series(minus_dm).ewm(span=adx_p, adjust=False).mean()

        df["plus_di"]  = (100 * pdi_raw / atr_s.replace(0, np.nan)).fillna(0)
        df["minus_di"] = (100 * mdi_raw / atr_s.replace(0, np.nan)).fillna(0)

        dx = (abs(df["plus_di"] - df["minus_di"]) /
              (df["plus_di"] + df["minus_di"]).replace(0, np.nan)) * 100
        df["adx"] = dx.ewm(span=adx_p, adjust=False).mean().fillna(0)

        # ── Volume ───────────────────────────────────────────────
        vol_p = min(config.VOLUME_AVERAGE_PERIOD, len(df))
        df["volume_sma"]   = df["volume"].rolling(vol_p, min_periods=1).mean()
        df["volume_ratio"] = (df["volume"] / df["volume_sma"].replace(0, np.nan)).fillna(1.0)

        return df


# ──────────────────────────────────────────────────────────────────
# DATA MANAGER
# ──────────────────────────────────────────────────────────────────

class DataManager:
    """
    Connects to broker via adapter, maintains rolling data for all indices.
    Thread-safe. Notifies registered callbacks on every tick.
    """

    def __init__(self):
        self._adapter: Optional[CombinedBrokerAdapter] = None
        self._states: Dict[str, IndexState] = {
            idx: IndexState(idx) for idx in config.INDICES
        }
        self._running        = False
        self._tick_thread:   Optional[threading.Thread] = None
        self._candle_thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable] = []
        self._db = get_db()
        self._last_purge_date: Optional[datetime] = None
        self._vix: float = 0.0          # India VIX — fetched every tick if available

    # ─── Public API ───────────────────────────────────────────────

    def add_update_callback(self, fn: Callable):
        self._callbacks.append(fn)

    def start(self) -> bool:
        self._adapter = get_adapter(config.BROKER)
        if not self._adapter.connect():
            logger.error(f"Broker {config.BROKER} connection failed")
            return False

        # ONE batch spot fetch for all indices (avoids rate limiting 4 separate calls)
        boot_spots: dict = {}
        if hasattr(self._adapter, "get_all_spot_prices"):
            boot_spots = self._adapter.get_all_spot_prices()

        # Bootstrap initial history
        for idx in config.INDICES:
            try:
                candles = self._adapter.get_historical_candles(
                    idx, config.CANDLE_INTERVAL_MINUTES, config.CANDLE_HISTORY_COUNT
                )
                futures = self._adapter.get_futures_candles(
                    idx, config.CANDLE_INTERVAL_MINUTES, config.CANDLE_HISTORY_COUNT
                )
                self._states[idx].update_candles(candles, futures)
                # Restore today's OI history from DB into futures_df
                try:
                    oi_rows = self._db.get_oi_history_intraday(
                        idx, config.CANDLE_INTERVAL_MINUTES
                    )
                    if oi_rows:
                        self._states[idx].restore_oi_history(oi_rows)
                        logger.info(f"Bootstrap {idx}: restored {len(oi_rows)} OI rows from DB")
                except Exception as e:
                    logger.debug(f"OI history restore [{idx}]: {e}")
                # Bootstrap option chain + expiry cache
                try:
                    chain_boot = self._adapter.get_option_chain(idx)
                    self._states[idx].update_option_chain(chain_boot)
                    self._refresh_expiry_cache(idx)
                except Exception:
                    pass
                # MTF timeframes
                candles_5m = self._adapter.get_historical_candles(
                    idx, 5, config.MTF_5M_HISTORY_COUNT
                )
                candles_15m = self._adapter.get_historical_candles(
                    idx, 15, config.MTF_15M_HISTORY_COUNT
                )
                self._states[idx].update_candles_5m(candles_5m)
                self._states[idx].update_candles_15m(candles_15m)
                # Use pre-fetched batch spot; fallback to latest candle close
                spot = boot_spots.get(idx, 0.0)
                if not spot or spot <= 0:
                    state = self._states[idx]
                    if state.df is not None and len(state.df) > 0:
                        spot = float(state.df.iloc[-1]["close"])
                        logger.info(f"Bootstrap {idx}: spot from API failed, using latest candle close {spot:.2f}")
                self._states[idx].update_spot(spot)
                prev_close = self._adapter.get_prev_day_close(idx)
                self._states[idx].prev_day_close = prev_close
                logger.info(f"Bootstrap {idx}: {len(candles)} candles "
                            f"(futures_vol={'yes' if futures else 'no'}), "
                            f"5m={len(candles_5m)}, 15m={len(candles_15m)}, "
                            f"spot={spot:.2f}, prev_close={prev_close:.2f}")
            except Exception as e:
                logger.error(f"Bootstrap error [{idx}]: {e}")

        # Purge stale data on startup
        self._run_daily_purge()

        self._running = True
        self._tick_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="TickThread"
        )
        self._candle_thread = threading.Thread(
            target=self._candle_loop, daemon=True, name="CandleThread"
        )
        self._tick_thread.start()
        self._candle_thread.start()
        logger.info(f"DataManager running — broker: {config.BROKER}")
        return True

    def stop(self):
        self._running = False
        if self._adapter:
            self._adapter.disconnect()

    def reconnect(self, broker_name: str) -> bool:
        """Hot-swap broker at runtime (called from Credentials tab)."""
        self.stop()
        config.BROKER = broker_name
        time.sleep(0.5)
        return self.start()

    # ─── State accessors ──────────────────────────────────────────

    def get_state(self, index_name: str) -> IndexState:
        return self._states[index_name]

    def get_df(self, index_name: str) -> Optional[pd.DataFrame]:
        return self._states[index_name].get_df()

    def get_spot(self, index_name: str) -> float:
        return self._states[index_name].spot_price

    def get_option_chain(self, index_name: str) -> Optional[OptionChain]:
        return self._states[index_name].get_option_chain()

    def get_prev_close(self, index_name: str) -> float:
        return self._states[index_name].prev_day_close

    def get_futures_df(self, index_name: str) -> Optional[pd.DataFrame]:
        return self._states[index_name].get_futures_df()

    def get_futures_price(self, index_name: str) -> float:
        return self._states[index_name].futures_price

    def get_df_5m(self, index_name: str) -> Optional[pd.DataFrame]:
        return self._states[index_name].get_df_5m()

    def get_df_15m(self, index_name: str) -> Optional[pd.DataFrame]:
        return self._states[index_name].get_df_15m()

    def get_vix(self) -> float:
        return self._vix

    def get_preopen_gap_pct(self, index_name: str) -> float:
        return self._states[index_name].preopen_gap_pct

    def get_all_directions(self) -> dict:
        """Return {index_name: 'BULLISH'|'BEARISH'|'NEUTRAL'} from latest DI values."""
        result = {}
        for idx, state in self._states.items():
            df = state.get_df()
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                pdi = float(last.get("plus_di", 0))
                mdi = float(last.get("minus_di", 0))
                adx = float(last.get("adx", 0))
                if adx >= 20:
                    result[idx] = "BULLISH" if pdi > mdi else "BEARISH"
                else:
                    result[idx] = "NEUTRAL"
            else:
                result[idx] = "NEUTRAL"
        return result

    def is_connected(self) -> bool:
        return self._adapter is not None and self._adapter.is_connected()

    # ─── Background threads ───────────────────────────────────────

    def _tick_loop(self):
        """Update spot price + option chain every DATA_FETCH_INTERVAL_SECONDS."""
        oc_counter = 0
        # How many ticks between OC refreshes (at least 1)
        oc_every_n = max(
            1,
            config.OC_REFRESH_INTERVAL_SECONDS // config.DATA_FETCH_INTERVAL_SECONDS,
        )
        while self._running:
            try:
                # ONE batch spot fetch for all indices to avoid rate limiting
                all_spots = {}
                if hasattr(self._adapter, "get_all_spot_prices"):
                    all_spots = self._adapter.get_all_spot_prices()
                elif hasattr(self._adapter, "get_spot_price"):
                    # Non-Fyers adapter: call once per index (no rate limit concern)
                    for idx in config.INDICES:
                        all_spots[idx] = self._adapter.get_spot_price(idx)

                # Fetch real-time futures OI + price in one batch call (Fyers only)
                all_futures_quotes: dict = {}
                if hasattr(self._adapter, "get_all_futures_quotes"):
                    try:
                        all_futures_quotes = self._adapter.get_all_futures_quotes()
                    except Exception as e:
                        logger.warning(f"Futures quotes tick error: {e}")

                # Fetch India VIX (Fyers only — best-effort)
                if hasattr(self._adapter, "get_vix"):
                    try:
                        vix = self._adapter.get_vix()
                        if vix > 0:
                            self._vix = vix
                    except Exception:
                        pass

                # Pre-opening window detection (IST)
                import config as _cfg
                _now_ist = datetime.now(_cfg.IST)
                _ist_time = _now_ist.time()
                from datetime import time as _time_cls
                _in_preopen = _time_cls(9, 0) <= _ist_time < _time_cls(9, 15)
                _at_open    = _time_cls(9, 15) <= _ist_time < _time_cls(9, 16)

                for idx in config.INDICES:
                    spot = all_spots.get(idx, 0.0)
                    # Fallback: use latest candle close when broker quotes fail
                    if not spot or spot <= 0:
                        state = self._states[idx]
                        if state.df is not None and len(state.df) > 0:
                            spot = float(state.df.iloc[-1]["close"])
                    self._states[idx].update_spot(spot)

                    # Update live OI into futures_df latest row
                    fq = all_futures_quotes.get(idx)
                    if fq:
                        self._states[idx].update_futures_oi_tick(
                            oi=fq["oi"], lp=fq["lp"]
                        )
                        # During pre-open (9:00–9:14): track futures LTP for gap feature
                        if _in_preopen and fq.get("lp", 0) > 0:
                            self._states[idx].update_preopen_futures_ltp(fq["lp"])
                        # At market open (9:15): freeze the pre-open snapshot
                        if _at_open:
                            self._states[idx].lock_preopen_snapshot()

                    if oc_counter % oc_every_n == 0:
                        chain = self._adapter.get_option_chain(idx)
                        self._states[idx].update_option_chain(chain)
                        self._persist_oc_snapshot(idx, chain)
                        self._refresh_expiry_cache(idx)

                oc_counter += 1
                for cb in self._callbacks:
                    try:
                        cb()
                    except Exception as e:
                        logger.warning(f"Callback error: {e}")
            except Exception as e:
                logger.error(f"Tick loop error: {e}")
            time.sleep(config.DATA_FETCH_INTERVAL_SECONDS)

    def _candle_loop(self):
        """Refresh full candle history every CANDLE_INTERVAL_MINUTES."""
        interval = config.CANDLE_INTERVAL_MINUTES * 60
        while self._running:
            try:
                for idx in config.INDICES:
                    candles = self._adapter.get_historical_candles(
                        idx, config.CANDLE_INTERVAL_MINUTES,
                        config.CANDLE_HISTORY_COUNT
                    )
                    futures = self._adapter.get_futures_candles(
                        idx, config.CANDLE_INTERVAL_MINUTES,
                        config.CANDLE_HISTORY_COUNT
                    )
                    self._states[idx].update_candles(candles, futures)
                    # MTF timeframes
                    candles_5m = self._adapter.get_historical_candles(
                        idx, 5, config.MTF_5M_HISTORY_COUNT
                    )
                    candles_15m = self._adapter.get_historical_candles(
                        idx, 15, config.MTF_15M_HISTORY_COUNT
                    )
                    self._states[idx].update_candles_5m(candles_5m)
                    self._states[idx].update_candles_15m(candles_15m)
                    self._persist_latest_candle(idx)
                    if futures:
                        self._persist_latest_futures_candle(idx, futures)
            except Exception as e:
                logger.error(f"Candle loop error: {e}")
            # Run daily purge at most once per calendar day
            self._run_daily_purge()
            time.sleep(interval)

    # ─── DB persistence ───────────────────────────────────────────

    def _persist_latest_candle(self, idx: str):
        try:
            df = self._states[idx].get_df()
            if df is None or len(df) == 0:
                return
            row  = df.iloc[-1]
            data = {
                "index_name":   idx,
                "timestamp":    row["timestamp"].to_pydatetime(),
                "interval":     config.CANDLE_INTERVAL_MINUTES,
                "open":         float(row["open"]),
                "high":         float(row["high"]),
                "low":          float(row["low"]),
                "close":        float(row["close"]),
                "volume":       float(row["volume"]),
                "candle_range": float(row.get("candle_range", 0)),
                "body_size":    float(row.get("body_size", 0)),
                "upper_wick":   float(row.get("upper_wick", 0)),
                "lower_wick":   float(row.get("lower_wick", 0)),
                "is_bullish":   bool(row.get("is_bullish", True)),
                "atr":          float(row.get("atr", 0)),
                "plus_di":      float(row.get("plus_di", 0)),
                "minus_di":     float(row.get("minus_di", 0)),
                "adx":          float(row.get("adx", 0)),
                "volume_sma":   float(row.get("volume_sma", 0)),
                "volume_ratio": float(row.get("volume_ratio", 1)),
            }
            self._db.save_candle(data)
        except Exception as e:
            logger.debug(f"Candle persist error [{idx}]: {e}")

    def _persist_oc_snapshot(self, idx: str, chain: OptionChain):
        try:
            snap = {
                "index_name":    idx,
                "timestamp":     chain.timestamp,
                "expiry_date":   chain.expiry,
                "spot_price":    float(chain.spot_price),
                "atm_strike":    float(chain.atm_strike),
                "total_call_oi": float(chain.total_call_oi),
                "total_put_oi":  float(chain.total_put_oi),
                "pcr":           float(chain.pcr),
                "pcr_volume":    float(chain.pcr_volume),
                "max_pain":      float(chain.max_pain),
                "chain_data":    [s.to_dict() for s in chain.strikes],
            }
            self._db.save_option_snapshot(snap)
        except Exception as e:
            logger.debug(f"OC persist error [{idx}]: {e}")

    def _persist_latest_futures_candle(self, idx: str, futures_candles: list):
        """
        Save the most recent futures candle with real-time OI to the DB.
        OI comes from in-memory futures_df (already updated by tick loop via
        get_all_futures_quotes), NOT from the history candles (which have no OI).
        """
        try:
            if not futures_candles:
                return
            c = futures_candles[-1]
            # Read live OI from in-memory state (updated each tick by quotes API)
            live_oi = 0.0
            fdf = self._states[idx].get_futures_df()
            if fdf is not None and len(fdf) > 0:
                live_oi = float(fdf.iloc[-1].get("oi", 0) or 0)
            data = {
                "index_name": idx,
                "timestamp":  c.timestamp,
                "interval":   c.interval,
                "open":       float(c.open),
                "high":       float(c.high),
                "low":        float(c.low),
                "close":      float(c.close),
                "volume":     float(c.volume),
                "oi":         live_oi,
                "is_futures": True,
            }
            self._db.save_candle(data)
            # Also update existing row's OI in case it was inserted earlier with OI=0
            if live_oi > 0:
                self._db.update_futures_candle_oi(idx, c.timestamp, c.interval, live_oi)
        except Exception as e:
            logger.debug(f"Futures candle persist error [{idx}]: {e}")

    def _refresh_expiry_cache(self, idx: str):
        """
        Fetch all expiry dates from broker and populate expiry_calendar cache.
        Falls back to reading expiry from the stored option chain if the adapter
        doesn't support get_expiry_dates() (e.g. mock / other brokers).
        """
        from data.expiry_calendar import update_from_broker, update_from_chain_expiry
        try:
            dates = self._adapter.get_expiry_dates(idx)
            if dates:
                update_from_broker(idx, dates)
                return
        except Exception:
            pass
        # Fallback: extract expiry string from the currently stored chain
        chain = self._states[idx].get_option_chain()
        if chain and chain.expiry:
            update_from_chain_expiry(idx, chain.expiry)

    def _run_daily_purge(self):
        """Purge old DB rows — at most once per calendar day."""
        today = datetime.now().date()
        if self._last_purge_date == today:
            return
        try:
            self._db.purge_old_data()
            self._last_purge_date = today
        except Exception as e:
            logger.warning(f"Daily purge failed: {e}")
