"""
ml/historical_trainer.py
────────────────────────────────────────────────────────────────────
Fetches historical Nifty/BankNifty candles from Fyers and generates
ML training data from OHLCV-computable features.

Usage:
    python -m ml.historical_trainer                    # last 90 days, all indices
    python -m ml.historical_trainer --days 180         # last 180 days
    python -m ml.historical_trainer --index NIFTY      # single index only
    python -m ml.historical_trainer --min-engines 2    # signal sensitivity

What it does:
    1. Fetches 3-min, 5-min, 15-min candles from Fyers
    2. Fetches India VIX history
    3. Computes all 73 OHLCV-derivable ML features
    4. Fires a signal wherever >= min_engines would have triggered
    5. Saves MLFeatureRecord rows to the database (label = -1, unlabeled)
    6. Labels all records with ATR heuristic (auto_labeler Priority 4)
    7. Prints a win-rate summary

Features computed  : 73 / 93 total
Features zeroed out: 20 option-chain features (pcr, iv_rank, etc.)
                     These will be filled by live data going forward.

Requires: Fyers authenticated (run main app and complete OAuth first).
          auth/fyers_token.json must exist and be valid.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("historical_trainer")

import config

# ─── Index config ─────────────────────────────────────────────────────────────

_INDEX_SYMBOLS = {
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "SENSEX":     "BSE:SENSEX-INDEX",
}
_INDEX_ENCODED = {"NIFTY": 0, "BANKNIFTY": 1, "MIDCPNIFTY": 2, "SENSEX": 3}
_VIX_SYMBOL    = "NSE:INDIA VIX"   # same symbol Fyers uses for quotes

# ─── Expiry schedule (SEBI circular Oct 1, 2024 — Circular 132/2024) ─────────
#
# Timeline:
#   Before Nov 20 2024  : All indices had weekly options
#                         NIFTY=Thu, BANKNIFTY=Thu, MIDCPNIFTY=Mon, SENSEX=Fri
#   Nov 20 2024 – Aug 31 2025 :
#                         NIFTY=Weekly Thu, BANKNIFTY=Monthly last-Thu,
#                         MIDCPNIFTY=Monthly last-Mon, SENSEX=Weekly Fri
#   Sep 1 2025 → current:
#                         NIFTY=Weekly Tue, BANKNIFTY=Monthly last-Tue,
#                         MIDCPNIFTY=Monthly last-Tue, SENSEX=Weekly Thu

_SEBI_WEEKLY_CUTOFF = date(2024, 11, 20)   # BANKNIFTY/MIDCPNIFTY weekly ends
_SEBI_DAY_CHANGE    = date(2025, 9,  1)    # NSE→Tue, BSE→Thu


def _expiry_config(index_name: str, on_date: date) -> dict:
    """
    Return {"is_weekly": bool, "weekday": int(0=Mon..4=Fri)} for the
    given index on the given date, reflecting all SEBI regime changes.
    """
    if on_date >= _SEBI_DAY_CHANGE:
        # Current regime — Sep 1 2025 onwards
        return {
            "NIFTY":      {"is_weekly": True,  "weekday": 1},  # Weekly Tue
            "BANKNIFTY":  {"is_weekly": False, "weekday": 1},  # Monthly last-Tue
            "MIDCPNIFTY": {"is_weekly": False, "weekday": 1},  # Monthly last-Tue
            "SENSEX":     {"is_weekly": True,  "weekday": 3},  # Weekly Thu
        }.get(index_name, {"is_weekly": True, "weekday": 1})

    if on_date >= _SEBI_WEEKLY_CUTOFF:
        # Transitional — Nov 20 2024 to Aug 31 2025
        return {
            "NIFTY":      {"is_weekly": True,  "weekday": 3},  # Weekly Thu
            "BANKNIFTY":  {"is_weekly": False, "weekday": 3},  # Monthly last-Thu
            "MIDCPNIFTY": {"is_weekly": False, "weekday": 0},  # Monthly last-Mon
            "SENSEX":     {"is_weekly": True,  "weekday": 4},  # Weekly Fri
        }.get(index_name, {"is_weekly": True, "weekday": 3})

    # Old regime — before Nov 20 2024 (all weekly)
    return {
        "NIFTY":      {"is_weekly": True, "weekday": 3},  # Weekly Thu
        "BANKNIFTY":  {"is_weekly": True, "weekday": 3},  # Weekly Thu
        "MIDCPNIFTY": {"is_weekly": True, "weekday": 0},  # Weekly Mon
        "SENSEX":     {"is_weekly": True, "weekday": 4},  # Weekly Fri
    }.get(index_name, {"is_weekly": True, "weekday": 3})


def _last_weekday_in_month(year: int, month: int, weekday: int) -> date:
    """Last occurrence of weekday (0=Mon..4=Fri) in the given month."""
    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _next_expiry_date(on_date: date, index_name: str) -> date:
    """Next expiry date for index on or after on_date (rolls on expiry day after 15:30)."""
    cfg = _expiry_config(index_name, on_date)
    wd  = cfg["weekday"]
    if cfg["is_weekly"]:
        days = (wd - on_date.weekday()) % 7
        return on_date + timedelta(days=days)
    else:
        # Monthly: last <wd> of current month; if past, go to next month
        exp = _last_weekday_in_month(on_date.year, on_date.month, wd)
        if exp < on_date:
            nm = on_date.month + 1 if on_date.month < 12 else 1
            ny = on_date.year if on_date.month < 12 else on_date.year + 1
            exp = _last_weekday_in_month(ny, nm, wd)
        return exp

# Fyers returns max ~100 days per intraday request → fetch in chunks
_MAX_DAYS_PER_REQUEST = 90


# ─── Fyers data fetcher ───────────────────────────────────────────────────────

def _connect_fyers():
    """Return connected FyersAdapter or raise RuntimeError."""
    from data.adapters.fyers_adapter import FyersAdapter
    adapter = FyersAdapter()
    ok = adapter.connect()
    if not ok or not adapter._fyers:
        raise RuntimeError(
            "Fyers not authenticated.\n"
            "  1. Run: python main.py\n"
            "  2. Go to Credentials tab → complete OAuth\n"
            "  3. Re-run this script"
        )
    return adapter


def _fetch_history(fyers_obj, symbol: str, resolution: str,
                   date_from: date, date_to: date) -> pd.DataFrame:
    """
    Fetch historical candles in chunks (Fyers limit: ~90 days per request).
    Returns DataFrame: timestamp(datetime), open, high, low, close, volume
    """
    all_candles = []
    chunk_start = date_from

    while chunk_start < date_to:
        chunk_end = min(chunk_start + timedelta(days=_MAX_DAYS_PER_REQUEST), date_to)
        try:
            resp = fyers_obj.history({
                "symbol":      symbol,
                "resolution":  resolution,
                "date_format": "1",
                "range_from":  chunk_start.strftime("%Y-%m-%d"),
                "range_to":    chunk_end.strftime("%Y-%m-%d"),
                "cont_flag":   "1",
            })
            candles = resp.get("candles", [])
            all_candles.extend(candles)
            logger.info(f"  {symbol} {resolution}m: {chunk_start}→{chunk_end} "
                        f"({len(candles)} bars)")
        except Exception as e:
            logger.warning(f"  Fetch error {symbol} {chunk_start}→{chunk_end}: {e}")
        chunk_start = chunk_end + timedelta(days=1)

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["ts", "open", "high", "low", "close", "volume"])
    # Convert unix → IST datetime
    df["timestamp"] = pd.to_datetime(df["ts"], unit="s") + timedelta(hours=5, minutes=30)
    df.drop(columns=["ts"], inplace=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

    # Market hours only: 09:15–15:30
    t = df["timestamp"].dt.time
    mkt_open  = datetime.strptime("09:15", "%H:%M").time()
    mkt_close = datetime.strptime("15:30", "%H:%M").time()
    df = df[(t >= mkt_open) & (t <= mkt_close)].reset_index(drop=True)
    return df


# ─── Indicator helpers ────────────────────────────────────────────────────────

def _wilder_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return _wilder_ema(tr, period)


def _adx_di(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    prev_high  = df["high"].shift(1)
    prev_low   = df["low"].shift(1)
    prev_close = df["close"].shift(1)

    move_up   = df["high"] - prev_high
    move_down = prev_low   - df["low"]
    plus_dm   = move_up.where((move_up > move_down) & (move_up > 0), 0.0)
    minus_dm  = move_down.where((move_down > move_up) & (move_down > 0), 0.0)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_s     = _wilder_ema(tr, period)
    plus_sm   = _wilder_ema(plus_dm, period)
    minus_sm  = _wilder_ema(minus_dm, period)
    plus_di   = 100 * plus_sm  / atr_s.replace(0, np.nan)
    minus_di  = 100 * minus_sm / atr_s.replace(0, np.nan)
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx       = _wilder_ema(dx, period)
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx})


def _vwap_intraday(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP — resets at start of each trading day."""
    typical      = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol       = typical * df["volume"]
    day_key      = df["timestamp"].dt.date.astype(str)
    cum_tpv      = df.groupby(day_key)["timestamp"].transform(lambda _: tp_vol.groupby(day_key).cumsum())
    cum_vol      = df.groupby(day_key)["timestamp"].transform(lambda _: df["volume"].groupby(day_key).cumsum())
    # Simpler approach: direct cumsum within each date group
    df2          = df.copy()
    df2["tp_vol"]= tp_vol
    df2["date_str"] = day_key
    df2["cum_tpv"]  = df2.groupby("date_str")["tp_vol"].cumsum()
    df2["cum_vol"]  = df2.groupby("date_str")["volume"].cumsum()
    return df2["cum_tpv"] / df2["cum_vol"].replace(0, np.nan)


def _choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
    atr_1     = _atr(df, 1)
    atr_sum   = atr_1.rolling(period).sum()
    high_max  = df["high"].rolling(period).max()
    low_min   = df["low"].rolling(period).min()
    pr        = (high_max - low_min).replace(0, np.nan)
    chop      = 100 * np.log10(atr_sum / pr) / np.log10(period)
    return chop.clip(0, 100)


def _efficiency_ratio(close: pd.Series, period: int = 10) -> pd.Series:
    net  = (close - close.shift(period)).abs()
    path = close.diff().abs().rolling(period).sum()
    return (net / path.replace(0, np.nan)).clip(0, 1)


def _slope(series: pd.Series, period: int = 5) -> pd.Series:
    xi = np.arange(period, dtype=float)
    def calc(x):
        if x.isna().any():
            return np.nan
        return float(np.polyfit(xi, x.values, 1)[0])
    return series.rolling(period).apply(calc, raw=False)


def _price_structure(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """1=BULLISH (HH+HL), -1=BEARISH (LH+LL), 0=NEUTRAL."""
    half = max(lookback // 2, 2)
    rh   = df["high"].rolling(half).max()
    rl   = df["low"].rolling(half).min()
    prh  = rh.shift(half)
    prl  = rl.shift(half)
    struct = pd.Series(0, index=df.index, dtype=int)
    struct[(rh > prh) & (rl > prl)] = 1
    struct[(rh < prh) & (rl < prl)] = -1
    return struct


# ─── Feature computation ─────────────────────────────────────────────────────

def compute_features(
    df3:   pd.DataFrame,
    df5:   Optional[pd.DataFrame],
    df15:  Optional[pd.DataFrame],
    vix_df: Optional[pd.DataFrame],
    index_name: str,
    other_dfs: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """
    Compute all 73 OHLCV-derivable ML features.
    Returns DataFrame with one row per 3-min candle.
    """
    df = df3.copy().sort_values("timestamp").reset_index(drop=True)

    # ── Engine 1: ATR + Compression ───────────────────────────────────────────
    df["atr"]              = _atr(df, 14)
    df["atr_pct_change"]   = df["atr"].pct_change(5).fillna(0) * 100
    df["candle_range"]     = df["high"] - df["low"]
    df["candle_range_5"]   = df["candle_range"].rolling(5).mean()
    df["candle_range_20"]  = df["candle_range"].rolling(20).mean()
    df["compression_ratio"]= df["candle_range_5"] / df["candle_range_20"].replace(0, np.nan)
    df["body_size"]        = (df["close"] - df["open"]).abs()
    df["upper_wick"]       = df["high"] - df[["open","close"]].max(axis=1)
    df["lower_wick"]       = df[["open","close"]].min(axis=1) - df["low"]

    # ── Engine 2: DI Momentum ─────────────────────────────────────────────────
    di3           = _adx_di(df, 14)
    df["plus_di"] = di3["plus_di"]
    df["minus_di"]= di3["minus_di"]
    df["adx"]     = di3["adx"]
    df["di_spread"]       = (df["plus_di"] - df["minus_di"]).abs()
    df["plus_di_slope"]   = _slope(df["plus_di"],  5)
    df["minus_di_slope"]  = _slope(df["minus_di"], 5)

    # ── Engine 4: Volume ──────────────────────────────────────────────────────
    df["volume_sma"]      = df["volume"].rolling(20).mean()
    df["volume_ratio"]    = df["volume"] / df["volume_sma"].replace(0, np.nan)
    df["volume_ratio_5"]  = df["volume_ratio"].rolling(5).mean()

    # ── Engine 5: Liquidity Trap (wick analysis) ──────────────────────────────
    df["liq_wick_ratio"]  = (df["upper_wick"] + df["lower_wick"]) / df["candle_range"].replace(0, np.nan)
    df["liq_volume_ratio"]= df["volume_ratio"]

    # ── Engine 7-new: VWAP Pressure ───────────────────────────────────────────
    df["vwap"]             = _vwap_intraday(df)
    df["dist_to_vwap_pct"] = (df["close"] - df["vwap"]) / df["vwap"].replace(0, np.nan) * 100
    df["vwap_vol_ratio"]   = df["volume_ratio"]
    prev_dist              = df["dist_to_vwap_pct"].shift(1)
    df["vwap_cross_up"]    = ((prev_dist < 0) & (df["dist_to_vwap_pct"] >= 0)).astype(int)
    df["vwap_cross_down"]  = ((prev_dist > 0) & (df["dist_to_vwap_pct"] <= 0)).astype(int)
    df["vwap_bounce"]      = (df["dist_to_vwap_pct"].abs() < 0.15).astype(int)
    df["vwap_rejection"]   = ((df["dist_to_vwap_pct"].abs() < 0.3) & (df["volume_ratio"] > 1.5)).astype(int)

    # ── Engine 8: Market Regime ───────────────────────────────────────────────
    df["regime_adx"]       = df["adx"]
    df["regime_atr_ratio"] = df["atr"] / df["atr"].rolling(20).mean().replace(0, np.nan)

    # ── Group A: Time context ─────────────────────────────────────────────────
    df["mins_since_open"]  = (
        df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute - (9 * 60 + 15)
    ).clip(lower=0)
    df["day_of_week"]      = df["timestamp"].dt.dayofweek
    # is_expiry and dte: date-aware — handles all SEBI regime changes
    def _is_expiry_row(ts):
        d   = ts.date()
        cfg = _expiry_config(index_name, d)
        wd  = cfg["weekday"]
        if d.weekday() != wd:
            return 0
        if cfg["is_weekly"]:
            return 1
        # Monthly: only the last <wd> of the month is expiry
        return 1 if d == _last_weekday_in_month(d.year, d.month, wd) else 0

    def _dte_row(ts):
        d   = ts.date()
        exp = _next_expiry_date(d, index_name)
        dte = (exp - d).days
        # If on expiry day and market is closed, roll to the next expiry
        if dte == 0 and ts.hour >= 15:
            exp2 = _next_expiry_date(d + timedelta(days=1), index_name)
            dte  = (exp2 - d).days
        return dte

    df["is_expiry"] = df["timestamp"].apply(_is_expiry_row)
    df["dte"]       = df["timestamp"].apply(_dte_row)

    def _session(m):
        if m < 30:  return 1   # opening
        if m < 120: return 2   # morning
        if m < 210: return 3   # midday
        return 4               # closing
    df["session"] = df["mins_since_open"].apply(_session)

    # ── Group B: Price context ────────────────────────────────────────────────
    # prev day close = first candle of each day's open
    df["_date"]            = df["timestamp"].dt.date
    daily_first_close      = df.groupby("_date")["close"].first()
    df["_prev_day_close"]  = df["_date"].map(lambda d: daily_first_close.get(d, np.nan)).shift(
        df.groupby("_date")["close"].transform("count")
    )
    # Simpler: use yesterday's last close
    df["_prev_close"]      = df.groupby("_date")["close"].transform("first").shift(1)
    df["spot_vs_prev_pct"] = (df["close"] - df["_prev_close"]) / df["_prev_close"].replace(0, np.nan) * 100
    df["atr_pct_spot"]     = df["atr"] / df["close"] * 100
    df["chop"]             = _choppiness(df, 14)
    df["efficiency_ratio"] = _efficiency_ratio(df["close"], 10)
    df["gap_pct"]          = (df["open"] - df["close"].shift(1)) / df["close"].shift(1).replace(0, np.nan) * 100
    df["preopen_gap_pct"]  = 0.0   # requires futures pre-open data

    # ── Group C: Candle patterns ──────────────────────────────────────────────
    df["is_bullish"]       = (df["close"] >= df["open"]).astype(int)
    df["prev_body_ratio"]  = (df["body_size"].shift(1) / df["candle_range"].shift(1).replace(0, np.nan)).clip(0, 1)
    df["prev_bullish"]     = df["is_bullish"].shift(1).fillna(0).astype(int)

    bull            = (df["is_bullish"] == 1)
    df["consec_bull"] = bull.groupby((~bull).cumsum()).cumsum().astype(int)
    bear            = (df["is_bullish"] == 0)
    df["consec_bear"] = bear.groupby((~bear).cumsum()).cumsum().astype(int)
    df["range_expansion"] = df["candle_range"] / df["candle_range_20"].replace(0, np.nan)

    # ── Group F: MTF DI / ADX (5m and 15m) ───────────────────────────────────
    for tf_df, suffix in [(df5, "5m"), (df15, "15m")]:
        cols = [f"adx_{suffix}", f"plus_di_{suffix}", f"minus_di_{suffix}",
                f"plus_di_slope_{suffix}", f"minus_di_slope_{suffix}"]
        if tf_df is None or tf_df.empty:
            for c in cols:
                df[c] = np.nan
            continue

        tf = tf_df.copy().sort_values("timestamp").reset_index(drop=True)
        di = _adx_di(tf, 14)
        tf[f"adx_{suffix}"]            = di["adx"]
        tf[f"plus_di_{suffix}"]        = di["plus_di"]
        tf[f"minus_di_{suffix}"]       = di["minus_di"]
        tf[f"plus_di_slope_{suffix}"]  = _slope(di["plus_di"],  5)
        tf[f"minus_di_slope_{suffix}"] = _slope(di["minus_di"], 5)

        df = pd.merge_asof(
            df.sort_values("timestamp"),
            tf[["timestamp"] + cols].sort_values("timestamp"),
            on="timestamp", direction="backward",
        ).sort_values("timestamp").reset_index(drop=True)

    # MTF reversal flags
    df["di_reversal_5m"]  = (
        (df["minus_di_5m"].diff()  < 0) & (df["plus_di"] > df["minus_di"])
    ).astype(int)
    df["di_reversal_15m"] = (
        (df["minus_di_15m"].diff() < 0) & (df["plus_di"] > df["minus_di"])
    ).astype(int)
    df["di_reversal_both"] = ((df["di_reversal_5m"] == 1) & (df["di_reversal_15m"] == 1)).astype(int)

    # ── Price Structure (5m and 15m) ──────────────────────────────────────────
    df["struct_3m"] = _price_structure(df, 10)

    for tf_df, col in [(df5, "struct_5m"), (df15, "struct_15m")]:
        if tf_df is None or tf_df.empty:
            df[col] = df["struct_3m"]
            continue
        tf = tf_df.copy().sort_values("timestamp").reset_index(drop=True)
        tf[col] = _price_structure(tf, 10)
        df = pd.merge_asof(
            df.sort_values("timestamp"),
            tf[["timestamp", col]].sort_values("timestamp"),
            on="timestamp", direction="backward",
        ).sort_values("timestamp").reset_index(drop=True)

    # ── Group G: VIX ─────────────────────────────────────────────────────────
    if vix_df is not None and not vix_df.empty:
        vix_s = vix_df[["timestamp", "close"]].rename(columns={"close": "vix"}).copy()
        df    = pd.merge_asof(
            df.sort_values("timestamp"),
            vix_s.sort_values("timestamp"),
            on="timestamp", direction="backward",
        ).sort_values("timestamp").reset_index(drop=True)
    else:
        df["vix"] = 15.0
    df["vix_high"] = (df["vix"] > 20).astype(int)

    # ── Group D: Multi-index correlation ─────────────────────────────────────
    if other_dfs:
        align_cols = []
        for other_name, odf in other_dfs.items():
            if odf is None or odf.empty:
                continue
            odi = _adx_di(odf.copy().sort_values("timestamp").reset_index(drop=True), 14)
            odf2 = odf.copy().sort_values("timestamp").reset_index(drop=True)
            odf2["_pdi"] = odi["plus_di"].values
            odf2["_mdi"] = odi["minus_di"].values
            col = f"_aligned_{other_name}"
            merged = pd.merge_asof(
                df[["timestamp", "plus_di", "minus_di"]].sort_values("timestamp"),
                odf2[["timestamp", "_pdi", "_mdi"]].sort_values("timestamp"),
                on="timestamp", direction="backward",
            )
            df[col] = (
                ((merged["plus_di"] > merged["minus_di"]) & (merged["_pdi"] > merged["_mdi"])) |
                ((merged["plus_di"] < merged["minus_di"]) & (merged["_pdi"] < merged["_mdi"]))
            ).astype(int)
            align_cols.append(col)
        if align_cols:
            df["aligned_indices"] = df[align_cols].sum(axis=1)
            df["market_breadth"]  = df["aligned_indices"] / len(align_cols)
            df.drop(columns=align_cols, inplace=True)
        else:
            df["aligned_indices"] = 0
            df["market_breadth"]  = 0.0
    else:
        df["aligned_indices"] = 0
        df["market_breadth"]  = 0.0

    # ── Index encoding ────────────────────────────────────────────────────────
    df["index_encoded"]         = _INDEX_ENCODED.get(index_name, 0)
    df["candle_completion_pct"] = 1.0   # historical candles are always complete

    # Cleanup temp columns
    for c in ["_date", "_prev_close", "_prev_day_close", "date_str",
              "cum_tpv", "cum_vol", "tp_vol", "struct_3m"]:
        df.drop(columns=[c], errors="ignore", inplace=True)

    return df.sort_values("timestamp").reset_index(drop=True)


# ─── Signal detection ─────────────────────────────────────────────────────────

def detect_signals(df: pd.DataFrame, min_engines: int = 2) -> pd.DataFrame:
    """
    Mark candles where ≥ min_engines simplified triggers fire.
    These become ML feature records. Direction determined by DI state.
    """
    df = df.copy()

    # Simplified engine triggers (mirror the real engine thresholds)
    df["compression_triggered"] = (
        (df["compression_ratio"] < 0.85) & (df["atr_pct_change"] < 0)
    ).fillna(False).astype(int)

    df["di_triggered"] = (
        (df["di_spread"] > 12) & (df["adx"] > 15)
    ).fillna(False).astype(int)

    df["volume_triggered"] = (
        df["volume_ratio"] > 1.4
    ).fillna(False).astype(int)

    df["vwap_triggered"] = (
        (df["vwap_cross_up"] == 1) | (df["vwap_cross_down"] == 1) |
        ((df["vwap_bounce"] == 1) & (df["volume_ratio"] > 1.2))
    ).fillna(False).astype(int)

    df["liquidity_trap_triggered"] = (
        (df["liq_wick_ratio"] > 0.6) & (df["volume_ratio"] > 1.3)
    ).fillna(False).astype(int)

    df["regime_triggered"] = (
        (df["regime_adx"] > 20) | (df["regime_atr_ratio"] > 1.2)
    ).fillna(False).astype(int)

    # Option chain / gamma / IV → 0 (no data)
    df["option_chain_triggered"] = 0
    df["gamma_triggered"]        = 0
    df["iv_triggered"]           = 0

    df["engines_count"] = (
        df["compression_triggered"] + df["di_triggered"] + df["volume_triggered"] +
        df["vwap_triggered"] + df["liquidity_trap_triggered"] + df["regime_triggered"]
    )

    # Direction from DI state
    df["direction"]         = "BULLISH"
    df.loc[df["minus_di"] > df["plus_di"], "direction"] = "BEARISH"
    df["direction_encoded"] = df["direction"].map({"BULLISH": 1, "BEARISH": -1})
    df["is_trade_signal"]   = 0   # historical treated as early-move level

    # Structure alignment
    s5  = df.get("struct_5m",  pd.Series(0, index=df.index))
    s15 = df.get("struct_15m", pd.Series(0, index=df.index))
    df["struct_5m_aligned"]  = (((s5  == 1) & (df["direction"] == "BULLISH")) |
                                ((s5  == -1) & (df["direction"] == "BEARISH"))).astype(int)
    df["struct_15m_aligned"] = (((s15 == 1) & (df["direction"] == "BULLISH")) |
                                ((s15 == -1) & (df["direction"] == "BEARISH"))).astype(int)
    df["struct_both_aligned"]= ((df["struct_5m_aligned"] == 1) &
                                (df["struct_15m_aligned"] == 1)).astype(int)

    # Fire signal: enough engines AND within trading hours AND VIX not extreme
    df["_fire"] = (
        (df["engines_count"] >= min_engines) &
        (df["mins_since_open"] >= 15) &     # skip 9:15–9:30 opening noise
        (df["mins_since_open"] <= 345) &    # skip after 3:30
        (df["vix"] <= 25)                   # skip when VIX extremely high
    )

    return df


# ─── Save to database ─────────────────────────────────────────────────────────

def save_features_to_db(df: pd.DataFrame, index_name: str) -> int:
    """Save signal rows as MLFeatureRecord (label=-1). Returns count saved."""
    from database.manager import get_db
    from database.models import MLFeatureRecord

    signal_df = df[df["_fire"]].copy()
    if signal_df.empty:
        return 0

    db    = get_db()
    saved = 0

    def f(row, col, default=0.0):
        v = row.get(col, default)
        return float(v) if (v is not None and not (isinstance(v, float) and math.isnan(v))) else default

    def i(row, col, default=0):
        v = row.get(col, default)
        return int(v) if (v is not None and not (isinstance(v, float) and math.isnan(v))) else default

    with db.get_session() as session:
        for _, row in signal_df.iterrows():
            record = MLFeatureRecord(
                index_name            = index_name,
                timestamp             = row["timestamp"].to_pydatetime(),
                label                 = -1,
                label_quality         = -1,
                label_direction       = 0,
                # Engine 1
                atr                   = f(row, "atr"),
                atr_pct_change        = f(row, "atr_pct_change"),
                compression_ratio     = f(row, "compression_ratio"),
                candle_range_5        = f(row, "candle_range_5"),
                candle_range_20       = f(row, "candle_range_20"),
                # Engine 2
                plus_di               = f(row, "plus_di"),
                minus_di              = f(row, "minus_di"),
                adx                   = f(row, "adx"),
                di_spread             = f(row, "di_spread"),
                plus_di_slope         = f(row, "plus_di_slope"),
                minus_di_slope        = f(row, "minus_di_slope"),
                # Engine 4
                volume_ratio          = f(row, "volume_ratio"),
                volume_ratio_5        = f(row, "volume_ratio_5"),
                # Engine 5
                liq_wick_ratio        = f(row, "liq_wick_ratio"),
                liq_volume_ratio      = f(row, "liq_volume_ratio"),
                # Engine 7-new VWAP
                vwap                  = f(row, "vwap"),
                dist_to_vwap_pct      = f(row, "dist_to_vwap_pct"),
                vwap_vol_ratio        = f(row, "vwap_vol_ratio"),
                vwap_cross_up         = bool(i(row, "vwap_cross_up")),
                vwap_cross_down       = bool(i(row, "vwap_cross_down")),
                vwap_bounce           = bool(i(row, "vwap_bounce")),
                vwap_rejection        = bool(i(row, "vwap_rejection")),
                # Engine 8
                regime_adx            = f(row, "regime_adx"),
                regime_atr_ratio      = f(row, "regime_atr_ratio"),
                # Trigger flags
                compression_triggered    = bool(i(row, "compression_triggered")),
                di_triggered             = bool(i(row, "di_triggered")),
                option_chain_triggered   = False,
                volume_triggered         = bool(i(row, "volume_triggered")),
                liquidity_trap_triggered = bool(i(row, "liquidity_trap_triggered")),
                gamma_triggered          = False,
                iv_triggered             = False,
                regime_triggered         = bool(i(row, "regime_triggered")),
                vwap_triggered           = bool(i(row, "vwap_triggered")),
                engines_count            = i(row, "engines_count"),
                candle_completion_pct    = 1.0,
                # Group A
                mins_since_open       = f(row, "mins_since_open"),
                session               = i(row, "session"),
                is_expiry             = i(row, "is_expiry"),
                day_of_week           = i(row, "day_of_week"),
                dte                   = i(row, "dte"),
                # Group B
                spot_vs_prev_pct      = f(row, "spot_vs_prev_pct"),
                atr_pct_spot          = f(row, "atr_pct_spot"),
                chop                  = f(row, "chop"),
                efficiency_ratio      = f(row, "efficiency_ratio"),
                gap_pct               = f(row, "gap_pct"),
                preopen_gap_pct       = 0.0,
                # Group C
                prev_body_ratio       = f(row, "prev_body_ratio"),
                prev_bullish          = i(row, "prev_bullish"),
                consec_bull           = i(row, "consec_bull"),
                consec_bear           = i(row, "consec_bear"),
                range_expansion       = f(row, "range_expansion"),
                # Group D
                aligned_indices       = i(row, "aligned_indices"),
                market_breadth        = f(row, "market_breadth"),
                # Group E (futures/OI — zeroed, not available)
                futures_oi_m          = 0.0,
                futures_oi_chg_pct    = 0.0,
                atm_oi_ratio          = 0.0,
                excess_basis_pct      = 0.0,
                futures_basis_slope   = 0.0,
                oi_regime             = -1,
                oi_regime_bullish     = 0,
                oi_regime_bearish     = 0,
                # Group F MTF
                adx_5m                = f(row, "adx_5m"),
                plus_di_5m            = f(row, "plus_di_5m"),
                minus_di_5m           = f(row, "minus_di_5m"),
                adx_15m               = f(row, "adx_15m"),
                plus_di_slope_5m      = f(row, "plus_di_slope_5m"),
                minus_di_slope_5m     = f(row, "minus_di_slope_5m"),
                plus_di_slope_15m     = f(row, "plus_di_slope_15m"),
                minus_di_slope_15m    = f(row, "minus_di_slope_15m"),
                di_reversal_5m        = i(row, "di_reversal_5m"),
                di_reversal_15m       = i(row, "di_reversal_15m"),
                di_reversal_both      = i(row, "di_reversal_both"),
                # Group G
                vix                   = f(row, "vix", 15.0),
                vix_high              = i(row, "vix_high"),
                # Price Structure
                struct_5m             = i(row, "struct_5m"),
                struct_15m            = i(row, "struct_15m"),
                struct_5m_aligned     = i(row, "struct_5m_aligned"),
                struct_15m_aligned    = i(row, "struct_15m_aligned"),
                struct_both_aligned   = i(row, "struct_both_aligned"),
                # Group H
                direction_encoded     = i(row, "direction_encoded"),
                index_encoded         = i(row, "index_encoded"),
                is_trade_signal       = 0,
            )
            session.add(record)
            saved += 1

    return saved


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run(indices: List[str], days: int, min_engines: int = 2):
    """Full pipeline: connect → fetch → compute → detect → save → label."""
    adapter    = _connect_fyers()
    fyers_obj  = adapter._fyers
    date_to    = date.today()
    date_from  = date_to - timedelta(days=days)

    # Fetch India VIX history once (daily candles — enough for intraday merge)
    logger.info("Fetching India VIX history...")
    try:
        vix_df = _fetch_history(fyers_obj, _VIX_SYMBOL, "D", date_from, date_to)
        if not vix_df.empty:
            # Broadcast each daily VIX value to cover the full trading day
            # so merge_asof can match intraday 3-min timestamps
            vix_df["timestamp"] = pd.to_datetime(vix_df["timestamp"].dt.date) + timedelta(hours=9, minutes=15)
            logger.info(f"VIX history: {len(vix_df)} days loaded")
        else:
            logger.warning("VIX history empty — using default VIX=15")
            vix_df = None
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e} — using default VIX=15")
        vix_df = None

    total_saved   = 0
    total_labeled = 0

    for index_name in indices:
        symbol = _INDEX_SYMBOLS.get(index_name)
        if not symbol:
            logger.warning(f"Unknown index: {index_name}")
            continue

        logger.info(f"\n{'='*55}")
        logger.info(f"Processing {index_name}  ({date_from} → {date_to})")
        logger.info(f"{'='*55}")

        try:
            df3  = _fetch_history(fyers_obj, symbol, "3",  date_from, date_to)
            df5  = _fetch_history(fyers_obj, symbol, "5",  date_from, date_to)
            df15 = _fetch_history(fyers_obj, symbol, "15", date_from, date_to)
        except Exception as e:
            logger.error(f"{index_name}: fetch failed — {e}")
            continue

        if df3.empty:
            logger.warning(f"{index_name}: no 3-min candles — skipping")
            continue

        logger.info(f"{index_name}: {len(df3)} candles loaded. Computing features...")

        # Fetch other indices for correlation
        other_dfs = {}
        for other_name, other_sym in _INDEX_SYMBOLS.items():
            if other_name == index_name:
                continue
            try:
                odf = _fetch_history(fyers_obj, other_sym, "3", date_from, date_to)
                if not odf.empty:
                    other_dfs[other_name] = odf
            except Exception:
                pass

        feat_df = compute_features(df3, df5, df15, vix_df, index_name, other_dfs)
        feat_df = detect_signals(feat_df, min_engines)

        n_signals = int(feat_df["_fire"].sum())
        logger.info(f"{index_name}: {n_signals} signal candles detected")

        if n_signals == 0:
            logger.warning(f"{index_name}: no signals — try --min-engines 1")
            continue

        saved = save_features_to_db(feat_df, index_name)
        total_saved += saved
        logger.info(f"{index_name}: {saved} records saved to DB")

    # Label all new records with ATR heuristic
    if total_saved > 0:
        logger.info(f"\nLabeling {total_saved} new records...")
        from ml.auto_labeler import AutoLabeler
        labeler       = AutoLabeler()
        total_labeled = labeler.run_once()
        logger.info(f"Labeled: {total_labeled} records")

        stats = labeler.get_label_stats()
        logger.info(
            f"\n{'='*55}\n"
            f"  ML Database Summary\n"
            f"{'='*55}\n"
            f"  Total records  : {stats['total']}\n"
            f"  Labeled        : {stats['labeled']}\n"
            f"  Unlabeled      : {stats['unlabeled']}\n"
            f"  Win rate       : {stats['accuracy_estimate']}%\n"
            f"  Quality SL     : {stats['quality_sl']}\n"
            f"  Quality T1     : {stats['quality_t1']}\n"
            f"  Quality T2     : {stats['quality_t2']}\n"
            f"  Quality T3     : {stats['quality_t3']}\n"
            f"{'='*55}"
        )

    return total_saved, total_labeled


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="NiftyTrader Historical ML Trainer — fetch Fyers data and train"
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Calendar days of history to fetch (default: 90, max: ~400 for intraday)"
    )
    parser.add_argument(
        "--index", type=str, default=None,
        help="Single index: NIFTY | BANKNIFTY | MIDCPNIFTY | SENSEX (default: all)"
    )
    parser.add_argument(
        "--min-engines", type=int, default=2,
        help="Min engines triggered to generate a signal record (default: 2)"
    )
    args = parser.parse_args()

    indices = [args.index.upper()] if args.index else list(_INDEX_SYMBOLS.keys())
    logger.info(
        f"Historical trainer starting\n"
        f"  Indices     : {indices}\n"
        f"  Days back   : {args.days}\n"
        f"  Min engines : {args.min_engines}\n"
    )

    saved, labeled = run(indices, args.days, args.min_engines)
    logger.info(f"\nDone — saved: {saved} records, labeled: {labeled}")
