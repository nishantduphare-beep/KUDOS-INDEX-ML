"""
engines/signal_aggregator.py
The brain of the system.

Combines engine outputs → Early Move Alert → Confirmed Trade Signal.

Triggering Engines (6):
  1. Compression      — price coiling, energy build-up
  2. DI Momentum      — directional pressure before ADX confirms
  3. Volume Pressure  — institutional accumulation / distribution
  4. Liquidity Trap   — stop-hunt sweep + reversal
  5. Gamma Levels     — MM delta-hedge walls and gamma flip
  6. Market Regime    — trending / ranging / volatile classification

Data-Only Engines (not counted toward trigger threshold):
  • Option Chain  — PCR, max pain, OI change saved as ML features only
  • IV Expansion  — iv_rank, avg_atm_iv saved as ML features only
    (both engines lagged price; ML learns their true predictive value)

Logic:
  • 4+ engines aligned → EARLY_MOVE alert
  • EARLY_MOVE + compression breakout + volume spike → TRADE_SIGNAL
"""

import logging
import threading
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, time as _time
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

import config
from data.structures import OptionChain
from engines.compression import CompressionDetector, CompressionResult
from engines.di_momentum import DIMomentumDetector, DIMomentumResult
from engines.option_chain import OptionChainDetector, OptionChainResult
from engines.volume_pressure import VolumePressureDetector, VolumePressureResult
from engines.liquidity_trap import LiquidityTrapDetector, LiquidityTrapResult
from engines.gamma_levels import GammaLevelsDetector, GammaLevelsResult
from engines.iv_expansion import IVExpansionDetector, IVExpansionResult
from engines.market_regime import MarketRegimeDetector, MarketRegimeResult
from engines.mtf_alignment import MTFAlignmentEngine, MTFResult
from engines.vwap_pressure import VWAPPressureDetector, VWAPResult
from engines.setup_screener import SetupScreener
from database.manager import get_db

logger = logging.getLogger(__name__)

# Use centralised IST from config (eliminates duplicate definitions across modules).
_IST = config.IST


@dataclass
class EarlyMoveAlert:
    index_name: str
    timestamp: datetime
    direction: str
    confidence_score: float
    engines_triggered: List[str]
    spot_price: float
    pcr: float
    atr: float
    raw_features: Dict[str, Any]
    engine_results: Dict[str, Any] = field(default_factory=dict)
    alert_type: str = "EARLY_MOVE"
    # S11 flag — set True by S11Monitor callback if this alert passes S11 condition.
    # alert_manager._dispatch() gates sound on this flag (Option A).
    is_s11: bool = False
    # MTF alignment info
    mtf_alignment:  str   = "NEUTRAL"  # STRONG/PARTIAL/NEUTRAL/WEAK/OPPOSING
    mtf_bias_5m:    str   = "NEUTRAL"
    mtf_bias_15m:   str   = "NEUTRAL"
    mtf_score_delta: float = 0.0
    # ML augmentation — populated by signal aggregator if model is ready
    ml_prediction: Optional[Any] = None    # MLPrediction object

    def __str__(self):
        ml_str = f"\nML Score  : {self.ml_prediction.ml_confidence:.1f}% ({self.ml_prediction.recommendation})" \
                 if self.ml_prediction and self.ml_prediction.is_available else ""
        return (
            f"⚡ EARLY MOVE ALERT [{self.index_name}]\n"
            f"Direction  : {self.direction}\n"
            f"Strategy   : {self.confidence_score:.1f}%"
            f"{ml_str}\n"
            f"Engines    : {', '.join(self.engines_triggered)}\n"
            f"Spot       : {self.spot_price:.2f} | PCR: {self.pcr:.3f}\n"
        )


@dataclass
class TradeSignal:
    index_name: str
    timestamp: datetime
    direction: str
    confidence_score: float
    engines_triggered: List[str]
    spot_price: float
    atm_strike: float
    pcr: float
    atr: float
    suggested_instrument: str
    entry_reference: float
    stop_loss_reference: float
    target_reference: float
    raw_features: Dict[str, Any]
    alert_type: str = "TRADE_SIGNAL"
    # MTF alignment info
    mtf_alignment:  str   = "NEUTRAL"
    mtf_bias_5m:    str   = "NEUTRAL"
    mtf_bias_15m:   str   = "NEUTRAL"
    mtf_score_delta: float = 0.0
    # Multi-target fields
    target1: float = 0.0
    target2: float = 0.0
    target3: float = 0.0
    expiry_display: str = ""    # e.g. "17 MAR 26"
    strike: float = 0.0
    option_type: str = "CE"
    # ML augmentation
    ml_prediction: Optional[Any] = None
    # DB id — set after save_alert() so OutcomeTracker can link outcomes
    alert_id: int = 0
    # Set True for the single candle-close confirmed copy of this signal
    is_confirmed: bool = False
    # S11 flag — set True by S11Monitor callback if this alert passes S11 condition.
    # alert_manager._dispatch() gates sound on this flag (Option A).
    is_s11: bool = False

    @property
    def action(self) -> str:
        return "BUY" if self.direction == "BULLISH" else "SELL"

    def recommendation_card(self) -> str:
        """Standard trade recommendation card format."""
        ml_line = ""
        if self.ml_prediction and self.ml_prediction.is_available:
            ml_line = (
                f"\nML Score   : {self.ml_prediction.ml_confidence:.0f}%"
                f"  ({self.ml_prediction.recommendation})"
            )
        pos   = self.raw_features.get("_position", {})
        lots  = pos.get("recommended_lots", 1)
        lot_s = pos.get("lot_size", "?")
        delta = pos.get("delta_used", 0.5)
        itm   = " [ITM]" if pos.get("itm_selected") else ""
        rolled = " [NEXT EXP]" if pos.get("expiry_rolled") else ""
        return (
            f"{self.action}\n"
            f"{self.index_name}  {self.expiry_display}{rolled}  "
            f"{int(self.strike)} {self.option_type}{itm}\n"
            f"Entry  {self.entry_reference:.0f}\n"
            f"SL     {self.stop_loss_reference:.0f}\n"
            f"T1     {self.target1:.0f}\n"
            f"T2     {self.target2:.0f}\n"
            f"T3     {self.target3:.0f}\n"
            f"Lots   {lots} × {lot_s}  (Δ {delta:.2f})\n"
            f"Strategy : {self.confidence_score:.1f}%{ml_line}"
        )

    def __str__(self):
        return self.recommendation_card()



class SignalAggregator:
    """
    Central orchestrator: runs all engines per tick, produces EarlyMoveAlert
    and TradeSignal, saves features to DB, and dispatches Telegram/sound alerts.

    Signal pipeline per tick
    ────────────────────────
    1. evaluate(index_name, df, chain) — called by DataManager tick thread
    2. Run 9 engines in parallel (each with 5s timeout + try-catch):
         Triggering (count toward MIN_ENGINES gate):
           Compression, DI Momentum, Volume Pressure,
           Liquidity Trap, Gamma Levels, Market Regime
         Data-only (ML features only, no gate vote):
           Option Chain, IV Expansion
         Context (confidence modifier, not gated):
           VWAP Pressure, MTF Alignment
    3. Count triggered engines → if ≥ MIN_ENGINES_FOR_ALERT → EarlyMoveAlert
    4. Confirm to TradeSignal when:
         • prior EarlyMoveAlert exists (≤ ALERT_MAX_AGE_CANDLES old)
         • compression breakout detected
         • volume spike confirmed
         • ADX ≥ TRADE_SIGNAL_MIN_ADX, |DI spread| ≥ TRADE_SIGNAL_MIN_DI_SPREAD
         • MTF alignment = STRONG (both 5m + 15m agree)
         • regime = TRENDING (if REQUIRE_TRENDING_REGIME)
         • VIX ≤ MAX_VIX_FOR_BULLISH_SIGNAL (BULLISH) or MAX_VIX_FOR_BEARISH_SIGNAL (BEARISH)
         • no active calendar event block
    5. Save ML feature row to DB (every evaluation, labeled later by AutoLabeler)
    6. Run SetupScreener — 23 named setups, saved to setup_alerts table

    Thread safety
    ─────────────
    evaluate() acquires a per-index lock (_lock[index_name]).
    All other public methods are read-only and lock-free.
    """

    def __init__(self):
        self._compression_engine  = CompressionDetector()
        self._di_engine           = DIMomentumDetector()
        self._oc_engine           = OptionChainDetector()
        self._vol_engine          = VolumePressureDetector()
        self._liq_engine          = LiquidityTrapDetector()
        self._gamma_engine        = GammaLevelsDetector()
        self._iv_engine           = IVExpansionDetector()
        self._regime_engine       = MarketRegimeDetector()
        self._vwap_engine         = VWAPPressureDetector()
        self._mtf_engine          = MTFAlignmentEngine()
        self._setup_screener      = SetupScreener()
        self._db = get_db()
        self._lock = threading.Lock()

        # Track in-flight early alerts per index
        self._active_alerts:    Dict[str, EarlyMoveAlert]     = {}
        self._prev_chains:      Dict[str, OptionChain]         = {}
        self._prev_compression: Dict[str, CompressionResult]   = {}

        # S3 fix: track last TRADE_SIGNAL time per index to prevent the same
        # setup from firing a signal every 5 s for the entire candle duration.
        self._last_signal_time: Dict[str, datetime] = {}

        # Suppress repeated "blocked" log lines — only log once per candle per index.
        self._last_mtf_block_log: Dict[str, datetime] = {}

        # 3-second debounce for early alerts — track last save time per index+direction.
        self._last_early_alert_time: Dict[str, datetime] = {}

        # TRADE_SIGNAL cooldown — one trade signal per candle per index+direction.
        self._last_trade_signal_time: Dict[str, datetime] = {}

        # Quiet-period tracking — detect when market breaks out of a dead zone.
        self._last_alert_time: Dict[str, datetime] = {}  # last EARLY_MOVE per index

        # Cache last engine + MTF results per index so dashboard can reuse them
        # without re-running all 8 engines a second time.
        self._last_engine_results: Dict[str, dict] = {}

        # Cross-index correlation — updated each evaluation for ML features.
        self._last_directions: Dict[str, str] = {}  # {index: BULLISH|BEARISH|NEUTRAL}

        # Item 9: Prediction confidence decay cache.
        # Stores last ML result per index so we can decay it based on time + spot movement.
        # Format: {index_name: {"prob": float, "direction": str, "ts": datetime, "spot": float}}
        self._last_ml_cache: Dict[str, dict] = {}

        # India VIX — updated by main_window from DataManager each tick.
        self._vix: float = 0.0

        # Diagnostic log dedup — tracks which index+candle combos have been logged.
        self._diag_logged: set = set()

    def evaluate(
        self,
        index_name: str,
        df: pd.DataFrame,
        chain: Optional[OptionChain],
        spot_price: float,
        df_5m: Optional[pd.DataFrame] = None,
        df_15m: Optional[pd.DataFrame] = None,
        prev_close: float = 0.0,
        futures_df: Optional[pd.DataFrame] = None,
        preopen_gap_pct: float = 0.0,
    ) -> Optional[Any]:  # Returns EarlyMoveAlert | TradeSignal | None
        """
        Full evaluation cycle.
        Returns the highest-priority signal generated, or None.
        """
        with self._lock:
            return self._run_evaluation(index_name, df, chain, spot_price,
                                        df_5m, df_15m, prev_close, futures_df,
                                        preopen_gap_pct)

    def set_vix(self, vix: float):
        with self._lock:
            self._vix = vix

    def set_cross_directions(self, directions: dict):
        """Called by main_window after all indices are evaluated."""
        with self._lock:
            self._last_directions.update(directions)

    def get_last_engine_results(self, index_name: str) -> Optional[dict]:
        """
        Return the cached engine results from the most recent evaluate() call
        for this index. Returns None if evaluate() has not been called yet.

        Shape: {"results": [EngineResult×8], "mtf_r": MTFResult,
                "triggered": int, "conf": float, "direction": str}
        """
        return self._last_engine_results.get(index_name)

    # ─── Market hours check ───────────────────────────────────────
    @staticmethod
    def _in_market_hours(index_name: str = "") -> bool:
        """
        Returns True if current IST time is within signal window.
        On expiry day, uses the earlier EXPIRY_DAY_SIGNAL_END_TIME cutoff.
        """
        if not config.ENFORCE_MARKET_HOURS:
            return True
        now_ist = datetime.now(_IST).time()
        try:
            h0, m0 = map(int, config.SIGNAL_START_TIME.split(":"))
            # Use earlier end time on expiry day to avoid noisy position-squaring signals
            end_time_str = config.SIGNAL_END_TIME
            if index_name:
                try:
                    from data.expiry_calendar import is_expiry_day
                    if is_expiry_day(index_name):
                        end_time_str = config.EXPIRY_DAY_SIGNAL_END_TIME
                except Exception:
                    pass
            h1, m1 = map(int, end_time_str.split(":"))
            return _time(h0, m0) <= now_ist <= _time(h1, m1)
        except Exception:
            return True

    @staticmethod
    def _is_data_fresh(df) -> bool:
        """
        Returns True only when the latest candle in df is recent enough to
        represent live market data.

        Threshold: CANDLE_INTERVAL_MINUTES × 2 (one full candle of buffer).
        This handles any case where data stops flowing — holidays, circuit
        breakers, unexpected halts, broker disconnects — without needing a
        hard-coded calendar.

        Mock adapter always generates datetime.now() candles so this passes
        transparently in test mode.
        """
        try:
            if df is None or len(df) == 0:
                return False
            last_ts = df["timestamp"].iloc[-1]
            if hasattr(last_ts, "to_pydatetime"):
                last_ts = last_ts.to_pydatetime()
            # Strip timezone if present (df timestamps are tz-naive local time)
            if hasattr(last_ts, "tzinfo") and last_ts.tzinfo is not None:
                last_ts = last_ts.replace(tzinfo=None)
            age_seconds = (datetime.now() - last_ts).total_seconds()
            max_age = config.CANDLE_INTERVAL_MINUTES * 60 * 2
            return age_seconds <= max_age
        except Exception:
            return True   # fail-open: don't block signals on unexpected errors

    def _run_evaluation(self, index_name, df, chain, spot_price,
                        df_5m=None, df_15m=None, prev_close=0.0, futures_df=None,
                        preopen_gap_pct=0.0):
        now = datetime.now()

        # ── Candle completion (forming-candle guard) ───────────────
        # Market opens at 09:15 IST. Each candle starts at a fixed boundary.
        # Signals fired in the first ~33% of a candle have incomplete
        # volume/range/OHLC — engine features are unreliable for Trade Signals.
        now_ist = datetime.now(_IST)
        mkt_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        secs_since_open = max(0.0, (now_ist - mkt_open).total_seconds())
        candle_width_secs = config.CANDLE_INTERVAL_MINUTES * 60
        secs_into_candle  = secs_since_open % candle_width_secs
        candle_completion_pct = round(secs_into_candle / candle_width_secs, 3)

        # ── Run all engines (6 triggering + 2 data-only + VWAP) ──
        # Each engine is wrapped with a 5s timeout and try-catch so a single
        # engine crash or hang cannot block/kill the entire evaluation loop.
        prev_chain       = self._prev_chains.get(index_name)
        prev_compression = self._prev_compression.get(index_name)

        def _run_engine(fn, *args, default=None):
            """Run fn(*args) with a 5s timeout; return default on error/timeout."""
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                    fut = _ex.submit(fn, *args)
                    return fut.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning(f"Engine {fn.__self__.__class__.__name__}.evaluate() timed out (5s) for {index_name}")
                return default
            except Exception as _e:
                logger.error(f"Engine {fn.__self__.__class__.__name__}.evaluate() error for {index_name}: {_e}")
                return default

        compression_r = _run_engine(self._compression_engine.evaluate, df,           default=CompressionResult())
        di_r          = _run_engine(self._di_engine.evaluate,          df,           default=DIMomentumResult())
        oc_r          = _run_engine(self._oc_engine.evaluate,          chain, prev_chain, default=OptionChainResult())
        vol_r         = _run_engine(self._vol_engine.evaluate,         df,           default=VolumePressureResult())
        liq_r         = _run_engine(self._liq_engine.evaluate,         df,           default=LiquidityTrapResult())
        gamma_r       = _run_engine(self._gamma_engine.evaluate,       chain, prev_chain, default=GammaLevelsResult())
        iv_r          = _run_engine(self._iv_engine.evaluate,          chain, prev_chain, default=IVExpansionResult())
        regime_r      = _run_engine(self._regime_engine.evaluate,      df,           default=MarketRegimeResult())
        vwap_r        = _run_engine(self._vwap_engine.evaluate,        df,           default=VWAPResult())

        # Store prev chain and compression for trend comparisons on next tick
        if chain:
            self._prev_chains[index_name] = chain
        self._prev_compression[index_name] = compression_r

        # B8 fix: market hours guard moved BEFORE DB writes.
        # Previously it fired AFTER all 8 engine signals were already persisted,
        # which filled the DB with off-hours noise. Now we skip writes entirely.
        if not self._in_market_hours(index_name):
            self._active_alerts.pop(index_name, None)
            return None

        # ── Data freshness guard ───────────────────────────────────
        # Block signals if the latest candle is older than 2× candle interval.
        # This automatically handles holidays, circuit breakers, unexpected
        # halts, and broker disconnects — no hard-coded calendar needed.
        # Mock adapter always stamps candles with datetime.now() so passes freely.
        if not self._is_data_fresh(df):
            self._active_alerts.pop(index_name, None)
            return None

        # ── Persist engine signals ─────────────────────────────────
        for engine_name, result in [
            ("compression",    compression_r),
            ("di_momentum",    di_r),
            ("option_chain",   oc_r),
            ("volume_pressure",vol_r),
            ("liquidity_trap", liq_r),
            ("gamma_levels",   gamma_r),
            ("iv_expansion",   iv_r),
            ("vwap_pressure",  vwap_r),
            ("market_regime",  regime_r),
        ]:
            self._db.save_engine_signal({
                "index_name": index_name,
                "timestamp": now,
                "engine_name": engine_name,
                "is_triggered": bool(result.is_triggered),
                "direction": result.direction,
                "strength": float(result.strength),
                "score": float(result.score),
                "features": result.features,
                "reason": result.reason,
            })

        # ── Directional consensus ──────────────────────────────────
        direction_votes = {"BULLISH": 0, "BEARISH": 0}
        triggered_engines = []
        total_score = 0.0

        for engine_name, result in [
            ("compression",    compression_r),
            ("di_momentum",    di_r),
            ("volume_pressure",vol_r),
            ("liquidity_trap", liq_r),
            ("gamma_levels",   gamma_r),
            ("vwap_pressure",  vwap_r),
            ("market_regime",  regime_r),
            # option_chain and iv_expansion are DATA-ONLY:
            # their detectors still run (oc_r / iv_r computed above) so their
            # features are saved to ML, but they do NOT count toward the
            # trigger threshold or confidence score.
        ]:
            if result.is_triggered:
                triggered_engines.append(engine_name)
                total_score += result.score
                if result.direction in direction_votes:
                    direction_votes[result.direction] += 1
                # Compression is NEUTRAL — counts as a triggered engine for the
                # 5-engine threshold but contributes no directional vote.
                # Previous 0.5+0.5 split cancelled out and inflated vote totals,
                # causing artificial ties that fell to DI tiebreaker unnecessarily.

        engines_triggered = len(triggered_engines)

        # BUG-2 fix: BULLISH default on tie was a systematic directional bias.
        # Use DI as tiebreaker — DI is the most direct trend direction indicator.
        if direction_votes["BULLISH"] > direction_votes["BEARISH"]:
            consensus_direction = "BULLISH"
        elif direction_votes["BEARISH"] > direction_votes["BULLISH"]:
            consensus_direction = "BEARISH"
        elif di_r.direction in ("BULLISH", "BEARISH"):
            consensus_direction = di_r.direction  # DI tiebreaker
        else:
            consensus_direction = "BULLISH"  # last resort

        # ── Confidence score ──────────────────────────────────────
        # option_chain and iv_expansion are data-only — exclude their weights
        # from the denominator so confidence reflects only the 6 active engines.
        max_possible = sum(config.CONFIDENCE_WEIGHTS.values())
        max_possible -= config.CONFIDENCE_WEIGHTS.get("iv_expansion", 10)
        max_possible -= config.CONFIDENCE_WEIGHTS.get("option_chain", 10)
        confidence = round((total_score / max(max_possible, 1)) * 100, 1)

        # ── MTF alignment (score modifier only, never blocks) ─────
        mtf_r = self._mtf_engine.evaluate(df_5m, df_15m, consensus_direction)
        confidence = round(min(100.0, max(0.0, confidence + mtf_r.score_delta)), 1)
        logger.debug(f"MTF [{index_name}]: {mtf_r.reason}")

        # Cache results so dashboard can read them without re-running engines
        self._last_engine_results[index_name] = {
            "results": [
                compression_r, di_r, oc_r, vol_r,
                liq_r, gamma_r, iv_r, vwap_r, regime_r,
            ],
            # Named refs so callers (e.g. confirmed-signal screener) can access by name
            "di_r":      di_r,
            "oc_r":      oc_r,
            "vol_r":     vol_r,
            "regime_r":  regime_r,
            "vwap_r":    vwap_r,
            "mtf_r":     mtf_r,
            "triggered": engines_triggered,
            "conf":      confidence,
            "direction": consensus_direction,
        }

        # Shared features for ML
        atr = float(df.iloc[-1]["atr"]) if df is not None and len(df) > 0 else 0.0
        pcr = float(chain.pcr) if chain else 0.0
        # Setup win rate + mins_since_last_signal — computed once, shared by _save_ml_features
        # and _get_ml_prediction so both the stored record and the live prediction are consistent.
        _setup_win_rate = 0.0
        try:
            _wr_map = self._db.get_rolling_setup_win_rates(index_name, lookback=20)
            if _wr_map:
                _setup_win_rate = max(_wr_map.values())
        except Exception:
            pass
        _last_ts_for_mins = self._last_trade_signal_time.get(index_name)
        _mins_since_last  = (
            max(0.0, (now - _last_ts_for_mins).total_seconds() / 60.0)
            if _last_ts_for_mins else 0.0
        )

        raw_features = {
            "compression":     compression_r.features,
            "di_momentum":     di_r.features,
            "option_chain":    oc_r.features,
            "volume_pressure": vol_r.features,
            "liquidity_trap":  liq_r.features,
            "gamma_levels":    gamma_r.features,
            "iv_expansion":    iv_r.features,
            "vwap_pressure":   vwap_r.features,
            "market_regime":   regime_r.features,
            "mtf_alignment":   mtf_r.features,
            "spot_price": spot_price,
            "atr": atr,
            "pcr": pcr,
            "candle_completion_pct": candle_completion_pct,
            # Performance context — available to _get_ml_prediction and _save_ml_features
            "index_name":             index_name,
            "setup_win_rate":         round(_setup_win_rate, 1),
            "mins_since_last_signal": round(_mins_since_last, 1),
        }

        # ── ML prediction — computed ONCE per tick, reused below ──
        # Cached here so the early-alert object, the DB save, and the
        # trade-signal gate all use the identical result without triple-calling.
        _tick_ml_pred = self._get_ml_prediction(raw_features, consensus_direction)

        # ── Early Move Alert: N+ engines aligned ──────────────────
        existing_alert = self._active_alerts.get(index_name)

        # Early Alert expiry: discard stale alerts that are too old to escalate.
        # A breakout 9+ minutes after the original alert is a different setup —
        # using the old alert as context would give wrong entry references and
        # confidence values. Force re-establishment of a fresh alert.
        if existing_alert:
            alert_age_secs = (now - existing_alert.timestamp).total_seconds()
            max_age_secs   = config.ALERT_MAX_AGE_CANDLES * config.CANDLE_INTERVAL_MINUTES * 60
            if alert_age_secs > max_age_secs:
                logger.debug(f"Alert expired [{index_name}]: age={alert_age_secs:.0f}s > {max_age_secs}s")
                self._active_alerts.pop(index_name, None)
                existing_alert = None

        if engines_triggered >= config.MIN_ENGINES_FOR_ALERT:
            alert = EarlyMoveAlert(
                index_name=index_name,
                timestamp=now,
                direction=consensus_direction,
                confidence_score=confidence,
                engines_triggered=triggered_engines,
                spot_price=spot_price,
                pcr=pcr,
                atr=atr,
                raw_features=raw_features,
                engine_results={
                    "compression":    {"triggered": bool(compression_r.is_triggered), "direction": compression_r.direction, "strength": float(compression_r.strength)},
                    "di_momentum":    {"triggered": bool(di_r.is_triggered),          "direction": di_r.direction,          "strength": float(di_r.strength)},
                    "option_chain":   {"triggered": bool(oc_r.is_triggered),          "direction": oc_r.direction,          "strength": float(oc_r.strength)},
                    "volume_pressure":{"triggered": bool(vol_r.is_triggered),         "direction": vol_r.direction,         "strength": float(vol_r.strength)},
                    "liquidity_trap": {"triggered": bool(liq_r.is_triggered),         "direction": liq_r.direction,         "strength": float(liq_r.strength)},
                    "gamma_levels":   {"triggered": bool(gamma_r.is_triggered),       "direction": gamma_r.direction,       "strength": float(gamma_r.strength)},
                    "iv_expansion":   {"triggered": bool(iv_r.is_triggered),          "direction": iv_r.direction,          "strength": float(iv_r.strength)},
                    "market_regime":  {"triggered": bool(regime_r.is_triggered),      "direction": regime_r.direction,      "strength": float(regime_r.strength)},
                }
            )

            # ── MTF fields ────────────────────────────────────────
            alert.mtf_alignment   = mtf_r.alignment
            alert.mtf_bias_5m     = mtf_r.bias_5m
            alert.mtf_bias_15m    = mtf_r.bias_15m
            alert.mtf_score_delta = mtf_r.score_delta
            # ── ML Augmentation ───────────────────────────────────
            alert.ml_prediction = _tick_ml_pred

            # ── Early Alert DB gate ───────────────────────────────────
            # UI always gets the alert object (live scanner updates every tick).
            # DB is written only when something meaningful changes:
            #   • First alert for this index
            #   • Direction flipped
            #   • Engines set changed (different engines triggered)
            #   • One full candle elapsed since last DB save (same direction)
            _alert_key     = f"{index_name}:{consensus_direction}"
            _last_early    = self._last_early_alert_time.get(_alert_key)
            _candle_secs   = config.CANDLE_INTERVAL_MINUTES * 60
            _engines_set   = set(triggered_engines) if triggered_engines else set()
            _prev_eng_set  = set(existing_alert.engines_triggered
                                 if existing_alert and existing_alert.engines_triggered
                                 else [])
            _is_new_alert = (
                existing_alert is None
                or existing_alert.direction != consensus_direction
                or _engines_set != _prev_eng_set
                or _last_early is None
                or (now - _last_early).total_seconds() >= _candle_secs
            )

            if _is_new_alert:
                _ml_pred = _tick_ml_pred
                alert_id = self._db.save_alert({
                    "index_name": index_name,
                    "timestamp": now,
                    "alert_type": "EARLY_MOVE",
                    "direction": consensus_direction,
                    "confidence_score": confidence,
                    "engines_triggered": triggered_engines,
                    "engines_count": engines_triggered,
                    "spot_price": spot_price,
                    "pcr": pcr,
                    "atr": atr,
                    "atm_strike": chain.atm_strike if chain else 0,
                    "raw_features": raw_features,
                    "ml_score": _ml_pred.ml_confidence if _ml_pred else None,
                    "ml_phase": _ml_pred.phase if _ml_pred else 1,
                })
                alert.alert_id = alert_id

                # Save ML features only for new alerts (non-fatal — alert fires regardless)
                try:
                    self._save_ml_features(alert_id, index_name, now,
                                           compression_r, di_r, oc_r, vol_r,
                                           liq_r, gamma_r, iv_r, regime_r,
                                           engines_triggered, chain, df,
                                           candle_completion_pct=candle_completion_pct,
                                           df_5m=df_5m, df_15m=df_15m,
                                           spot_price=spot_price, prev_close=prev_close,
                                           futures_df=futures_df,
                                           consensus_direction=consensus_direction,
                                           vwap=vwap_r,
                                           preopen_gap_pct=preopen_gap_pct)
                except Exception as _mle:
                    logger.warning(f"ML feature save failed (alert still fired): {_mle}")

                # ── SetupScreener — evaluate all 23 named setups ──────
                # Runs on every new candle alert (throttled same as ML features).
                # Saves one row per triggered setup to setup_alerts table.
                try:
                    _setup_hits = self._setup_screener.evaluate(
                        index_name=index_name,
                        direction=consensus_direction,
                        timestamp=now,
                        spot_price=spot_price,
                        atr=atr,
                        engines_count=engines_triggered,
                        di_r=di_r,
                        vol_r=vol_r,
                        oc_r=oc_r,
                        regime_r=regime_r,
                        vwap_r=vwap_r,
                        mtf_r=mtf_r,
                        pcr=pcr,
                    )
                    if _setup_hits:
                        self._db.save_setup_alerts(_setup_hits, alert_id=alert_id)
                        logger.debug(
                            f"SetupScreener [{index_name}]: "
                            f"{len(_setup_hits)} setups saved "
                            f"(alert_id={alert_id})"
                        )
                except Exception as _se:
                    logger.warning(f"SetupScreener save failed (non-fatal): {_se}")

                self._last_early_alert_time[_alert_key] = now
                self._last_alert_time[index_name] = now
                logger.info(f"EARLY MOVE ALERT: {index_name} {consensus_direction} "
                            f"({engines_triggered} engines, {confidence:.1f}%)")
            else:
                # Carry forward the existing alert_id so Trade Signal escalation
                # can reference the correct DB record.
                alert.alert_id = existing_alert.alert_id if hasattr(existing_alert, "alert_id") else None
                logger.debug(f"EARLY MOVE db-throttled (same candle) [{index_name}] {consensus_direction}")

            self._active_alerts[index_name] = alert

            # ── Confirmed Trade Signal ─────────────────────────────
            # Gate conditions (all checked BEFORE any DB write):
            #   Path A — Normal: existing early alert + momentum expansion
            #   Path B — Quiet breakout: no early alert but strong burst from dead zone

            # CRITICAL-1: block Trade Signal in RANGING market.
            _is_ranging = getattr(regime_r, "ranging", False)

            # Trending Regime gate — require TRENDING regime for Trade Signals.
            # Tested: TRENDING = 55.8% WR vs 12.8% base (4.37x lift, 6-day live data).
            # AMBIGUOUS / VOLATILE / RANGING are all blocked when this is enabled.
            _regime_label  = getattr(regime_r, "regime", "")
            _trending_ok   = (
                not config.REQUIRE_TRENDING_REGIME
                or _regime_label == "TRENDING"
            )

            # Index direction filter — block low-win-rate directions per index.
            # BANKNIFTY bull WR=21-32% vs bear WR=71% (6-day live data).
            _dir_filter    = getattr(config, "INDEX_DIRECTION_FILTER", {})
            _allowed_dir   = _dir_filter.get(index_name, "")
            _direction_ok  = (
                not _allowed_dir
                or consensus_direction == _allowed_dir
            )

            # Index filter — block known low-win-rate indices entirely,
            # require higher confidence for strict indices (data-driven).
            _index_blocked  = index_name in config.SIGNAL_BLOCKED_INDICES
            _index_strict   = index_name in config.SIGNAL_STRICT_INDICES
            _strict_conf_ok = confidence >= config.SIGNAL_STRICT_MIN_CONFIDENCE

            # Volume gate — low-volume signals have 41% win rate (below 1x avg).
            _vol_ratio    = float(vol_r.features.get("volume_ratio", 1.0))
            _vol_ratio_ok = _vol_ratio >= config.SIGNAL_MIN_VOLUME_RATIO

            # PCR gate — PCR < 0.7 has 11% win rate, near-random noise.
            _pcr_ok = pcr >= config.SIGNAL_MIN_PCR

            # Forming-candle guard: block Trade Signal in first 33% of candle.
            _candle_ok = candle_completion_pct >= config.SIGNAL_MIN_CANDLE_COMPLETION

            # MTF opposing block
            _mtf_opposing = (config.MTF_BLOCK_ON_OPPOSING
                             and mtf_r.alignment == "OPPOSING")
            if _mtf_opposing:
                _last_log = self._last_mtf_block_log.get(index_name)
                _log_cooldown = config.CANDLE_INTERVAL_MINUTES * 60
                if not _last_log or (now - _last_log).total_seconds() >= _log_cooldown:
                    logger.info(f"Trade Signal blocked: MTF OPPOSING [{index_name}] "
                                f"5m={mtf_r.bias_5m} 15m={mtf_r.bias_15m}")
                    self._last_mtf_block_log[index_name] = now

            # Momentum expansion: candle range > ATR × multiplier
            _last_row = df.iloc[-1] if df is not None and len(df) > 0 else None
            _atr_val  = float(_last_row.get("atr", 0))  if _last_row is not None else 0
            _c_range  = float(_last_row.get("high", 0) - _last_row.get("low", 0)) if _last_row is not None else 0
            _range_ok = _c_range > _atr_val * config.BREAKOUT_ATR_MULTIPLIER

            # Volume confirmation — relaxed for cash indices (volume often 0 from broker).
            # Accept: actual spike OR volume engine triggered OR range expansion alone.
            # Per-index+direction cooldown — check BEFORE any DB write.
            _ts_key  = f"{index_name}:{consensus_direction}"
            _last_ts = self._last_trade_signal_time.get(_ts_key)
            _cooldown_secs = config.CANDLE_INTERVAL_MINUTES * 60
            _ts_ready = (_last_ts is None
                         or (now - _last_ts).total_seconds() >= _cooldown_secs)

            # Quiet-breakout detection — fires without prior early alert when the
            # market has been silent (dead zone) and a strong candle suddenly appears.
            _last_any = self._last_alert_time.get(index_name)
            _quiet_mins = ((now - _last_any).total_seconds() / 60) if _last_any else 999
            _is_quiet_breakout = (
                _quiet_mins >= 10                              # 10+ min silence
                and _c_range > _atr_val * 1.5                 # extra-strong candle (1.5×ATR)
                and di_r.is_triggered                         # DI confirming direction
                and engines_triggered >= config.MIN_ENGINES_FOR_ALERT  # minimum engines
            )

            # Path A: normal escalation — existing early alert + momentum.
            # vol_ok removed: cash indices (NIFTY/BN/etc.) have near-zero broker
            # volume so the gate was permanently False. 5-engine threshold already
            # provides sufficient quality filter.
            _path_a = (existing_alert is not None
                       and existing_alert.direction == consensus_direction
                       and engines_triggered >= config.MIN_ENGINES_FOR_SIGNAL)

            # Path B: quiet breakout — no prior early alert needed
            _path_b = (_is_quiet_breakout and not existing_alert)

            # ML gate: compute prediction before gate check so it can block signals.
            # Only active in Phase 2 (model trained). Phase 1 = no model = always pass.
            # Uses session-specific threshold: opening session (1) is stricter (0.55)
            # than morning/midday (2/3) which use the base 0.50.
            _ml_pred = _tick_ml_pred
            _now_ist_h = datetime.now(_IST).hour
            _now_ist_m = datetime.now(_IST).minute
            if   _now_ist_h < 9 or (_now_ist_h == 9 and _now_ist_m < 30): _session_now = 0
            elif _now_ist_h == 9 or (_now_ist_h == 10 and _now_ist_m == 0): _session_now = 1
            elif _now_ist_h < 12: _session_now = 2
            elif _now_ist_h < 14: _session_now = 3
            else: _session_now = 4
            _session_thresholds = getattr(config, "ML_SESSION_GATE_THRESHOLDS", {})
            _ml_threshold = _session_thresholds.get(
                _session_now,
                getattr(config, "ML_SIGNAL_GATE_THRESHOLD", 0.50)
            )
            _ml_gate_ok = (
                _ml_pred is None
                or not _ml_pred.is_available
                or _ml_pred.probability >= _ml_threshold
            )

            # ── Event calendar gate ───────────────────────────────
            # Block TRADE_SIGNAL during RBI/Fed/Budget windows.
            # IV spikes before events → premium too expensive to buy.
            # Early alerts still fire (ML data collection unaffected).
            _event_name = None
            _event_ok   = True
            if config.SIGNAL_BLOCK_ON_EVENT:
                try:
                    from data.event_calendar import get_active_event
                    _event_name = get_active_event(datetime.now(_IST))
                    _event_ok   = (_event_name is None)
                except Exception:
                    pass
            if not _event_ok:
                _last_log = self._last_mtf_block_log.get(f"{index_name}:event")
                _log_cooldown = config.CANDLE_INTERVAL_MINUTES * 60
                if not _last_log or (now - _last_log).total_seconds() >= _log_cooldown:
                    logger.info(f"Trade Signal blocked: EVENT WINDOW [{index_name}] "
                                f"event='{_event_name}'")
                    self._last_mtf_block_log[f"{index_name}:event"] = now

            # ── VIX gate (direction-aware) ─────────────────────────
            # WHY direction-aware (not a single flat threshold):
            #   VIX spikes WITH market falls — a BEARISH signal in high VIX
            #   is self-consistent (fear confirms the move). BULLISH signals
            #   in high VIX fight prevailing fear AND pay elevated call premiums.
            #
            # BULLISH → MAX_VIX_FOR_BULLISH_SIGNAL (20): calls too expensive above 20
            # BEARISH → MAX_VIX_FOR_BEARISH_SIGNAL (28): puts outperform on fear spikes
            #
            # See config.py VIX GATE section for full rationale.
            _vix_ok = True
            if config.SIGNAL_BLOCK_ON_HIGH_VIX and self._vix > 0:
                _vix_threshold = (
                    config.MAX_VIX_FOR_BEARISH_SIGNAL if consensus_direction == "BEARISH"
                    else config.MAX_VIX_FOR_BULLISH_SIGNAL
                )
                _vix_ok = self._vix <= _vix_threshold
                if not _vix_ok:
                    _last_log = self._last_mtf_block_log.get(f"{index_name}:vix")
                    _log_cooldown = config.CANDLE_INTERVAL_MINUTES * 60
                    if not _last_log or (now - _last_log).total_seconds() >= _log_cooldown:
                        logger.info(
                            f"Trade Signal blocked: HIGH VIX [{index_name}] "
                            f"vix={self._vix:.1f} > {_vix_threshold:.0f} "
                            f"({consensus_direction} threshold)"
                        )
                        self._last_mtf_block_log[f"{index_name}:vix"] = now

            # ADX gate — trend must be strong enough on the 3m candle.
            # Data: MIDCP 10:23 had ADX=15.89 (barely above floor), SL hit in 4 min.
            _adx_val = float(di_r.features.get("adx", 0))
            _adx_ok  = _adx_val >= config.TRADE_SIGNAL_MIN_ADX

            # DI direction gate — +DI must lead for BULLISH, -DI must lead for BEARISH.
            # di_spread = plus_di - minus_di; negative on a BULLISH signal = bearish conviction.
            # Data: MIDCP 10:23 had di_spread=-3.4 on a BULLISH signal — -DI was dominant.
            _di_spread = float(di_r.features.get("di_spread", 0))
            _di_ok = (
                (consensus_direction == "BULLISH" and _di_spread >= config.TRADE_SIGNAL_MIN_DI_SPREAD) or
                (consensus_direction == "BEARISH" and _di_spread <= -config.TRADE_SIGNAL_MIN_DI_SPREAD)
            )

            # MTF strength gate — require STRONG (both 5m + 15m agree).
            # PARTIAL / NEUTRAL / WEAK / OPPOSING all blocked.
            # Data: the only T3 win today had MTF=STRONG; the SL at 10:23 had MTF=PARTIAL.
            _mtf_strong_ok = (
                not config.TRADE_SIGNAL_REQUIRE_MTF_STRONG
                or mtf_r.alignment == "STRONG"
            )

            # Diagnostic: log why trade signal didn't fire (once per candle per index).
            # Prune _diag_logged to only the current minute's keys so the set stays bounded
            # regardless of session length (max entries = 4 indices × 1 per minute = tiny).
            _cur_minute = now.strftime("%H%M")
            self._diag_logged = {k for k in self._diag_logged if k.endswith(_cur_minute)}

            if engines_triggered >= config.MIN_ENGINES_FOR_SIGNAL:
                _diag_key = f"{index_name}:diag:{_cur_minute}"
                if _diag_key not in self._diag_logged:
                    self._diag_logged.add(_diag_key)
                    _ml_prob = f"{_ml_pred.probability:.2f}" if (_ml_pred and _ml_pred.is_available) else "n/a"
                    logger.info(
                        f"TRADE GATE [{index_name}] path_a={_path_a} path_b={_path_b} "
                        f"ranging={_is_ranging} candle_ok={_candle_ok} "
                        f"mtf={mtf_r.alignment}(ok={_mtf_strong_ok}) "
                        f"adx={_adx_val:.1f}(ok={_adx_ok}) "
                        f"di_spread={_di_spread:.1f}(ok={_di_ok}) "
                        f"ts_ready={_ts_ready} "
                        f"existing={'yes' if existing_alert else 'no'} "
                        f"vol_ratio={_vol_ratio:.2f}(ok={_vol_ratio_ok}) "
                        f"pcr={pcr:.2f}(ok={_pcr_ok}) "
                        f"index_blocked={_index_blocked} strict_ok={_strict_conf_ok} "
                        f"ml_prob={_ml_prob}(thr={_ml_threshold:.2f},ok={_ml_gate_ok}) "
                        f"event_ok={_event_ok} vix={self._vix:.1f}(thr={_vix_threshold:.0f},ok={_vix_ok}) "
                        f"regime={_regime_label}(trending_ok={_trending_ok}) "
                        f"dir_filter={_allowed_dir or 'any'}(ok={_direction_ok}) "
                        f"engines={engines_triggered}"
                    )

            if ((_path_a or _path_b)
                    and not _is_ranging
                    and _trending_ok
                    and _direction_ok
                    and _candle_ok
                    and _mtf_strong_ok
                    and _adx_ok
                    and _di_ok
                    and _ts_ready
                    and not _index_blocked
                    and (not _index_strict or _strict_conf_ok)
                    and _vol_ratio_ok
                    and _pcr_ok
                    and _ml_gate_ok
                    and _event_ok
                    and _vix_ok):

                if _path_b:
                    logger.info(f"QUIET BREAKOUT detected [{index_name}] "
                                f"{consensus_direction} after {_quiet_mins:.0f}min silence")

                signal = self._build_trade_signal(
                    index_name, now, consensus_direction, confidence,
                    triggered_engines, spot_price, chain, atr, pcr,
                    raw_features
                )
                signal.mtf_alignment   = mtf_r.alignment
                signal.mtf_bias_5m     = mtf_r.bias_5m
                signal.mtf_bias_15m    = mtf_r.bias_15m
                signal.mtf_score_delta = mtf_r.score_delta
                signal.ml_prediction = _ml_pred  # reuse — already computed above
                # Remove active alert (signal consumed it)
                self._active_alerts.pop(index_name, None)

                # Update cooldown BEFORE saving (prevents double-fire in same tick)
                self._last_trade_signal_time[_ts_key] = now
                self._last_signal_time[index_name] = now

                # Persist trade signal (non-fatal — signal fires regardless)
                _ml = signal.ml_prediction
                try:
                    trade_alert_id = self._db.save_alert({
                        "index_name": index_name,
                        "timestamp": now,
                        "alert_type": "TRADE_SIGNAL",
                        "direction": consensus_direction,
                        "confidence_score": confidence,
                        "engines_triggered": triggered_engines,
                        "engines_count": engines_triggered,
                        "spot_price": spot_price,
                        "pcr": pcr,
                        "atr": atr,
                        "atm_strike": signal.atm_strike,
                        "suggested_instrument": signal.suggested_instrument,
                        "entry_reference": signal.entry_reference,
                        "stop_loss_reference": signal.stop_loss_reference,
                        "target_reference": getattr(signal, "target1", signal.target_reference),
                        "target1": getattr(signal, "target1", None),
                        "target2": getattr(signal, "target2", None),
                        "target3": getattr(signal, "target3", None),
                        "ml_score": _ml.ml_confidence if _ml else None,
                        "ml_phase": _ml.phase if _ml else 1,
                        "raw_features": raw_features,
                    })
                    signal.alert_id = trade_alert_id
                except Exception as _dbe:
                    logger.warning(f"Trade signal DB save failed (signal still fired): {_dbe}")
                    signal.alert_id = None

                # Save ML features for TRADE_SIGNAL — labeled from TradeOutcome later
                # is_trade_signal=1 lets the model distinguish trade setups from early moves
                if signal.alert_id:
                    try:
                        self._save_ml_features(
                            signal.alert_id, index_name, now,
                            compression_r, di_r, oc_r, vol_r,
                            liq_r, gamma_r, iv_r, regime_r,
                            engines_triggered, chain, df,
                            candle_completion_pct=candle_completion_pct,
                            df_5m=df_5m, df_15m=df_15m,
                            spot_price=spot_price, prev_close=prev_close,
                            futures_df=futures_df,
                            consensus_direction=consensus_direction,
                            is_trade_signal=1,
                            vwap=vwap_r,
                            preopen_gap_pct=preopen_gap_pct,
                        )
                    except Exception as _mle:
                        logger.debug(f"ML features save (trade signal) failed: {_mle}")

                    # ── SetupScreener for TRADE_SIGNAL ─────────────────
                    # Save setup_alerts linked to the TRADE alert_id so that
                    # auto_labeler can propagate high-quality TradeOutcome labels
                    # (T1/T2/T3/SL from real option P&L) directly to setup_alerts.
                    # Early-move setup_alerts (above) use ATR heuristic labels only.
                    try:
                        _ts_hits = self._setup_screener.evaluate(
                            index_name=index_name,
                            direction=consensus_direction,
                            timestamp=now,
                            spot_price=spot_price,
                            atr=atr,
                            engines_count=engines_triggered,
                            di_r=di_r,
                            vol_r=vol_r,
                            oc_r=oc_r,
                            regime_r=regime_r,
                            vwap_r=vwap_r,
                            mtf_r=mtf_r,
                            pcr=pcr,
                        )
                        if _ts_hits:
                            self._db.save_setup_alerts(_ts_hits, alert_id=signal.alert_id)
                            logger.debug(
                                f"SetupScreener [TRADE {index_name}]: "
                                f"{len(_ts_hits)} setups saved "
                                f"(trade_alert_id={signal.alert_id})"
                            )
                    except Exception as _se:
                        logger.warning(f"SetupScreener (trade signal) save failed: {_se}")

                logger.info(f"TRADE SIGNAL: {index_name} {consensus_direction} "
                            f"→ {signal.suggested_instrument} "
                            f"({'quiet breakout' if _path_b else 'escalation'})")
                return signal

            # Track direction for cross-index ML features
            self._last_directions[index_name] = consensus_direction
            # Return alert to UI every tick (live scanner confidence updates).
            # DB writes are already throttled above via _is_new_alert gate.
            return alert

        else:
            # Not enough engines — clear stale alert
            if index_name in self._active_alerts:
                logger.debug(f"Clearing stale alert for {index_name}")
                self._active_alerts.pop(index_name, None)

        # Track direction for cross-index correlation on next tick
        self._last_directions[index_name] = consensus_direction if engines_triggered >= config.MIN_ENGINES_FOR_ALERT else "NEUTRAL"
        return None

    @staticmethod
    def _detect_structure(df) -> str:
        """
        Detect HH/HL/LH/LL price structure from a candle DataFrame.
        Returns 'BULLISH', 'BEARISH', or 'NEUTRAL'.

        Logic:
          - Find pivot swing highs and lows (each bar vs its neighbours)
          - HH + HL = BULLISH structure (buyers defending higher lows)
          - LH + LL = BEARISH structure (sellers capping at lower highs)
          - Mixed or insufficient = NEUTRAL

        Intentionally NOT used as a gate — result is saved as ML feature only.
        """
        try:
            if df is None or len(df) < 4:
                return "NEUTRAL"

            highs = df["high"].tolist() if hasattr(df, "columns") else [c.high for c in df]
            lows  = df["low"].tolist()  if hasattr(df, "columns") else [c.low  for c in df]

            def find_pivots(vals, is_high):
                pivots = []
                for i in range(1, len(vals) - 1):
                    if is_high:
                        if vals[i] >= vals[i - 1] and vals[i] >= vals[i + 1]:
                            pivots.append(vals[i])
                    else:
                        if vals[i] <= vals[i - 1] and vals[i] <= vals[i + 1]:
                            pivots.append(vals[i])
                return pivots

            swing_highs = find_pivots(highs, True)
            swing_lows  = find_pivots(lows,  False)

            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                hh = swing_highs[-1] > swing_highs[-2]
                hl = swing_lows[-1]  > swing_lows[-2]
                lh = swing_highs[-1] < swing_highs[-2]
                ll = swing_lows[-1]  < swing_lows[-2]
                if hh and hl: return "BULLISH"
                if lh and ll: return "BEARISH"
                return "NEUTRAL"
            elif len(swing_highs) >= 2:
                return "BULLISH" if swing_highs[-1] > swing_highs[-2] else "BEARISH"
            elif len(swing_lows) >= 2:
                return "BULLISH" if swing_lows[-1] > swing_lows[-2] else "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def _get_ml_prediction(self, raw_features: dict, direction: str):
        """
        Build a flat feature dict for ML prediction.

        Item 9: applies confidence decay to stale cached predictions.
        A cached prediction is stale when:
          - More than 3 candle-lengths have elapsed (≥ 9 min for 3-min candles), OR
          - Spot has moved more than 1× ATR since the prediction was made.
        When stale, probability decays toward 0.5 (neutral) linearly.
        A fresh inference always replaces the cache.

        Uses explicit per-engine key mapping (same as _save_ml_features) to avoid
        silent overwrites when two engine feature dicts share a key name.
        """
        try:
            from ml.model_manager import get_model_manager
            comp   = raw_features.get("compression",     {}) or {}
            di     = raw_features.get("di_momentum",     {}) or {}
            oc     = raw_features.get("option_chain",    {}) or {}
            vol    = raw_features.get("volume_pressure", {}) or {}
            liq    = raw_features.get("liquidity_trap",  {}) or {}
            gamma  = raw_features.get("gamma_levels",    {}) or {}
            iv     = raw_features.get("iv_expansion",    {}) or {}
            vwap   = raw_features.get("vwap_pressure",   {}) or {}
            regime = raw_features.get("market_regime",   {}) or {}

            # Build flat dict with explicit column names — mirrors _save_ml_features exactly.
            # Each value is sourced from the correct engine to prevent cross-engine collisions.
            flat: dict = {
                # Engine 1: Compression
                "atr":               comp.get("atr_current", 0),
                "atr_pct_change":    comp.get("atr_slope", 0),
                "compression_ratio": comp.get("range_ratio", 1),
                "candle_range_5":    comp.get("recent_avg_range", 0),
                "candle_range_20":   comp.get("avg_20_range", 0),
                # Engine 2: DI Momentum (sole source for adx, plus_di, minus_di)
                "plus_di":           di.get("plus_di", 0),
                "minus_di":          di.get("minus_di", 0),
                "adx":               di.get("adx", 0),   # di_momentum only, not regime
                "di_spread":         di.get("di_spread", 0),
                "plus_di_slope":     di.get("spread_change", 0),
                "minus_di_slope":    di.get(
                    "minus_di_change",
                    di.get("minus_di_slope", -di.get("spread_change", 0))
                ),
                # Engine 3: Option Chain (sole source for iv_rank = avg_call_iv)
                "pcr":               oc.get("pcr", raw_features.get("pcr", 0)),
                "pcr_change":        oc.get("pcr_change", 0),
                "call_oi_change":    oc.get("call_oi_change", 0),
                "put_oi_change":     oc.get("put_oi_change", 0),
                "iv_rank":           oc.get("avg_call_iv", 0),  # option_chain only
                "max_pain_distance": oc.get("max_pain_distance", 0),
                # Engine 4: Volume Pressure (sole source for volume_ratio)
                "volume_ratio":      vol.get("volume_ratio", 1),   # vol_pressure only
                "volume_ratio_5":    vol.get("vol_5_mean_ratio", 1),
                "is_small_candle":   vol.get("stealth_pattern", False),
                # Engine 5: Liquidity Trap (liq_volume_ratio distinct from volume_ratio)
                "liq_wick_ratio":    liq.get("wick_ratio_up", liq.get("wick_ratio_dn", 0)),
                "liq_volume_ratio":  liq.get("volume_ratio", 1),
                # Engine 6: Gamma Levels
                "dist_to_gamma_wall": gamma.get("dist_to_gamma_wall", 1),
                "dist_to_call_wall":  gamma.get("dist_to_call_wall", 1),
                "dist_to_put_wall":   gamma.get("dist_to_put_wall", 1),
                # Engine 7: IV Expansion (avg_atm_iv, not iv_rank — that comes from oc above)
                "iv_expanding":      iv.get("iv_expanding", False),
                "iv_skew_ratio":     iv.get("iv_skew_ratio", 1.0),
                "avg_atm_iv":        iv.get("avg_atm_iv", 0),
                "iv_change_pct":     iv.get("iv_change_pct", 0),
                # VWAP Pressure
                "vwap":              vwap.get("vwap", 0),
                "dist_to_vwap_pct":  vwap.get("dist_to_vwap_pct", 0),
                "vwap_cross_up":     vwap.get("vwap_cross_up", False),
                "vwap_cross_down":   vwap.get("vwap_cross_down", False),
                "vwap_bounce":       vwap.get("vwap_bounce", False),
                "vwap_rejection":    vwap.get("vwap_rejection", False),
                "vwap_vol_ratio":    vwap.get("vwap_vol_ratio", 0),
                # Engine 8: Market Regime (regime_adx distinct from adx above)
                "market_regime":     regime.get("regime", ""),
                "regime_adx":        regime.get("adx", 0),   # regime engine only
                "regime_atr_ratio":  regime.get("atr_ratio", 1),
                # Top-level scalars
                "spot_price":              raw_features.get("spot_price", 0),
                "candle_completion_pct":   raw_features.get("candle_completion_pct", 0),
                # Group I: Historical performance context (pre-computed, passed through raw_features)
                "setup_win_rate":          raw_features.get("setup_win_rate", 0.0),
                "mins_since_last_signal":  raw_features.get("mins_since_last_signal", 0.0),
            }
            index_name  = raw_features.get("index_name", "")
            current_spot = raw_features.get("spot_price", 0.0)
            current_atr  = flat.get("atr", 20.0) or 20.0
            now          = datetime.now()

            prediction = get_model_manager().predict(flat, direction, index_name=index_name)

            # ── Item 9: Cache + decay ────────────────────────────
            # Always store the freshly computed prediction.
            if prediction and prediction.is_available:
                self._last_ml_cache[index_name] = {
                    "prob":      prediction.probability,
                    "direction": direction,
                    "ts":        now,
                    "spot":      current_spot,
                    "atr":       current_atr,
                }
            elif index_name in self._last_ml_cache:
                # No fresh inference available — apply decay to the cached result.
                cached     = self._last_ml_cache[index_name]
                elapsed_s  = (now - cached["ts"]).total_seconds()
                max_age_s  = config.CANDLE_INTERVAL_MINUTES * 60 * 3   # 3 candles
                spot_move  = abs(current_spot - cached["spot"]) if current_spot > 0 else 0.0
                atr_moved  = spot_move / cached["atr"] if cached["atr"] > 0 else 0.0

                # Decay factor: 0.0 = fully fresh, 1.0 = fully stale (prob → 0.5)
                time_decay  = min(1.0, elapsed_s / max(max_age_s, 1))
                spot_decay  = min(1.0, atr_moved)          # 1 ATR move = fully stale
                decay       = max(time_decay, spot_decay)

                if decay > 0.1:   # only decay if meaningfully stale
                    orig_prob    = cached["prob"]
                    decayed_prob = orig_prob + decay * (0.5 - orig_prob)
                    # Re-emit the cached prediction with decayed probability
                    if prediction and not prediction.is_available:
                        # Construct a decayed copy only if direction still matches
                        if cached["direction"] == direction and decay < 1.0:
                            from ml.model_manager import MLPrediction
                            decayed_conf = round(decayed_prob * 100, 1)
                            rec = (f"STRONG_{direction}" if decayed_prob >= 0.70
                                   else f"MODERATE_{direction}" if decayed_prob >= 0.55
                                   else "WEAK_SIGNAL" if decayed_prob >= 0.45
                                   else "LOW_CONFIDENCE")
                            prediction = MLPrediction(
                                is_available  = True,
                                probability   = decayed_prob,
                                ml_confidence = decayed_conf,
                                recommendation= rec,
                                direction     = direction,
                                phase         = 2,
                            )

            return prediction
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"ML prediction skipped: {e}")
            return None

    def _build_trade_signal(
        self, index_name, timestamp, direction, confidence,
        engines, spot, chain, atr, pcr, features
    ) -> TradeSignal:
        """
        Build a structured trade recommendation:
          BUY/SELL  IndexName  DD MMM YY  Strike  CE/PE
          Entry / SL / T1 / T2 / T3  — all as option prices

        Improvements:
          - ITM strike for high-confidence setups (better delta, less theta)
          - Next-week expiry on expiry day (avoids rapid theta decay)
          - Liquidity guard: fallback to ATM if chosen strike has low OI
          - Position sizing: recommended lots based on capital and risk %
          - Delta adjusted to actual strike (ATM=0.50, ITM=0.62)
        """
        _sym = config.SYMBOL_MAP.get(index_name, {})
        gap        = _sym.get("strike_gap", 50)
        lot_size   = _sym.get("lot_size", 1)
        atm_strike = chain.atm_strike if chain else round(spot / gap) * gap
        option_type = "CE" if direction == "BULLISH" else "PE"

        # ── Expiry selection ───────────────────────────────────────
        # On expiry day (DTE ≤ threshold), roll to next week's expiry to avoid
        # severe theta decay that makes even correct directional trades unprofitable.
        expiry = chain.expiry if chain else ""
        try:
            from data.expiry_calendar import days_to_option_expiry, all_option_expiries
            dte = days_to_option_expiry(index_name)
            if dte <= config.EXPIRY_ROLL_DTE_THRESHOLD:
                all_exp = all_option_expiries(index_name)
                if len(all_exp) >= 2:
                    next_expiry_date = all_exp[1]
                    expiry = next_expiry_date.strftime("%d%b%Y").upper()
                    logger.debug(f"Expiry rolled to next week [{index_name}]: "
                                 f"DTE={dte} ≤ {config.EXPIRY_ROLL_DTE_THRESHOLD} → {expiry}")
        except Exception:
            pass  # expiry calendar not yet populated — keep nearest

        # ── Strike selection ───────────────────────────────────────
        # Strong trend (confidence above threshold) → 1-strike ITM for better
        # delta (0.60-0.65 vs 0.50) and lower theta risk per ATR move.
        # ATM is always used as fallback if ITM has insufficient OI.
        use_itm = confidence >= config.STRONG_TREND_CONFIDENCE
        if use_itm:
            if direction == "BULLISH":
                candidate_strike = atm_strike - gap   # ITM call = below ATM
            else:
                candidate_strike = atm_strike + gap   # ITM put  = above ATM
        else:
            candidate_strike = atm_strike

        # ── Liquidity guard ────────────────────────────────────────
        # Verify the chosen strike has sufficient OI; fallback to ATM if not.
        strike = candidate_strike
        if chain and chain.strikes and use_itm:
            strike_oi = 0.0
            for s in chain.strikes:
                if s.strike == candidate_strike:
                    strike_oi = s.call_oi if option_type == "CE" else s.put_oi
                    break
            if strike_oi < config.MIN_OPTION_OI_FOR_TRADE:
                logger.debug(f"ITM strike {candidate_strike} OI={strike_oi:.0f} "
                             f"< {config.MIN_OPTION_OI_FOR_TRADE} — falling back to ATM")
                strike = atm_strike

        # Delta: ITM ≈ 0.62, ATM ≈ 0.50
        delta = 0.62 if (strike != atm_strike) else 0.50

        # ── Get option LTP from chain ──────────────────────────────
        option_ltp = 0.0
        if chain and chain.strikes:
            for s in chain.strikes:
                if s.strike == strike:
                    option_ltp = s.call_ltp if option_type == "CE" else s.put_ltp
                    break
        if option_ltp <= 0:
            option_ltp = max(10.0, atr * delta)

        # ── Option price targets using delta-adjusted ATR ──────────
        opt_per_atr = atr * delta
        entry = option_ltp
        sl    = max(1.0, entry - opt_per_atr * 0.8)   # -0.8 ATR
        t1    = entry + opt_per_atr * 1.0              # +1.0 ATR
        t2    = entry + opt_per_atr * 1.5              # +1.5 ATR
        t3    = entry + opt_per_atr * 2.2              # +2.2 ATR

        # Round to nearest 0.5 for clean display
        def _r(v): return round(round(v * 2) / 2, 1)
        entry = _r(entry)
        sl    = _r(sl)
        t1    = _r(t1)
        t2    = _r(t2)
        t3    = _r(t3)

        # ── Position sizing ────────────────────────────────────────
        # Max loss per lot = (entry - SL) × lot_size
        # Recommended lots = floor(risk_budget / max_loss_per_lot)
        risk_budget    = config.DEFAULT_CAPITAL * config.RISK_PER_TRADE_PCT
        loss_per_lot   = max(0.5, entry - sl) * lot_size
        recommended_lots = max(1, int(risk_budget // loss_per_lot))

        # ── Expiry display & instrument symbol ─────────────────────
        expiry_display = self._format_expiry_display(expiry, timestamp)
        expiry_compact = expiry[:7] if len(expiry) >= 7 else expiry
        instrument     = f"{index_name}{expiry_compact}{int(strike)}{option_type}"

        signal = TradeSignal(
            index_name=index_name,
            timestamp=timestamp,
            direction=direction,
            confidence_score=confidence,
            engines_triggered=engines,
            spot_price=spot,
            atm_strike=atm_strike,
            pcr=pcr,
            atr=atr,
            suggested_instrument=instrument,
            entry_reference=entry,
            stop_loss_reference=sl,
            target_reference=t1,
            target1=t1,
            target2=t2,
            target3=t3,
            expiry_display=expiry_display,
            strike=strike,
            option_type=option_type,
            raw_features=features,
        )
        # Attach position sizing as extra metadata
        signal.raw_features["_position"] = {
            "recommended_lots": recommended_lots,
            "lot_size":         lot_size,
            "risk_budget":      risk_budget,
            "loss_per_lot":     round(loss_per_lot, 1),
            "delta_used":       delta,
            "itm_selected":     strike != atm_strike,
            "expiry_rolled":    expiry != (chain.expiry if chain else expiry),
        }
        return signal

    @staticmethod
    def _format_expiry_display(expiry: str, fallback_dt) -> str:
        """Convert 'DDMMMYYYY' → 'DD MMM YY' for display."""
        try:
            from datetime import datetime as _dt
            # Common formats from brokers: "27MAR2025", "2025-03-27", "27-Mar-2025"
            for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y", "%d%b%y"):
                try:
                    d = _dt.strptime(expiry.strip().upper(), fmt.upper())
                    return d.strftime("%d %b %y").upper()
                except ValueError:
                    continue
        except Exception:
            pass
        # Fallback: use next Thursday
        from datetime import date, timedelta
        today = date.today()
        days  = (3 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days)).strftime("%d %b %y").upper()

    # Maps index name → integer code for ML feature
    _INDEX_ENCODING = {
        "NIFTY": 0, "BANKNIFTY": 1, "MIDCPNIFTY": 2, "SENSEX": 3,
    }

    def _save_ml_features(
        self, alert_id, index_name, timestamp,
        comp, di, oc, vol, liq, gamma, iv, regime,
        engines_count, chain, df,
        candle_completion_pct: float = 0.0,
        df_5m=None, df_15m=None,
        spot_price: float = 0.0, prev_close: float = 0.0,
        futures_df=None, consensus_direction: str = "NEUTRAL",
        is_trade_signal: int = 0,
        vwap=None,
        preopen_gap_pct: float = 0.0,
    ):
        """Save denormalized ML feature vector — all 7 engines + extended context features."""

        # ── Group A: Time context ─────────────────────────────────
        try:
            from data.expiry_calendar import days_to_option_expiry, is_expiry_day
            dte          = days_to_option_expiry(index_name)
            _is_expiry   = int(is_expiry_day(index_name))
        except Exception:
            dte, _is_expiry = 7, 0
        now_ist         = datetime.now(_IST)
        mkt_open_ist    = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        mins_since_open = max(0.0, (now_ist - mkt_open_ist).total_seconds() / 60.0)
        day_of_week     = now_ist.weekday()   # 0=Mon … 4=Fri
        _h, _m          = now_ist.hour, now_ist.minute
        if   _h < 9 or (_h == 9 and _m < 30):  session = 0   # pre-signal
        elif _h == 9 or (_h == 10 and _m == 0): session = 1   # opening
        elif _h < 12:                            session = 2   # morning
        elif _h < 14:                            session = 3   # midday
        else:                                    session = 4   # closing

        # ── Group B: Price context ────────────────────────────────
        atr_val          = comp.features.get("atr_current", 0)
        spot_vs_prev_pct = ((spot_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        atr_pct_spot     = (atr_val / spot_price * 100) if spot_price > 0 else 0.0
        chop_val         = regime.features.get("chop", 50.0)
        er_val           = regime.features.get("er", 0.5)
        # gap: first candle open vs prev close
        gap_pct = 0.0
        if df is not None and len(df) > 0 and prev_close > 0:
            today_open = float(df.iloc[0]["open"]) if "open" in df.columns else 0.0
            if today_open > 0:
                gap_pct = (today_open - prev_close) / prev_close * 100

        # Pre-opening gap: futures LTP captured 9:00–9:14 vs prev close.
        # Frozen at session start — same value for all alerts throughout the day.
        # preopen_gap_pct > 0 = gap-up open expected, < 0 = gap-down expected.
        # 0.0 means either no gap OR pre-open data not yet captured (early in session).
        # Used as an ML feature only — no gate.

        # ── Group C: Candle patterns ──────────────────────────────
        prev_body_ratio = 0.5
        prev_bullish    = 0
        consec_bull     = 0
        consec_bear     = 0
        range_expansion = 1.0
        if df is not None and len(df) >= 2:
            p = df.iloc[-2]
            p_range = float(p["high"] - p["low"]) if (p["high"] - p["low"]) > 0 else 1
            prev_body_ratio = abs(float(p["close"]) - float(p["open"])) / p_range
            prev_bullish    = 1 if float(p["close"]) >= float(p["open"]) else 0
            # consecutive candles
            for i in range(len(df) - 2, max(len(df) - 11, -1), -1):
                row = df.iloc[i]
                if float(row["close"]) >= float(row["open"]):
                    if consec_bear > 0: break
                    consec_bull += 1
                else:
                    if consec_bull > 0: break
                    consec_bear += 1
            cur_range   = float(df.iloc[-1]["high"] - df.iloc[-1]["low"])
            avg_range5  = comp.features.get("recent_avg_range", cur_range) or cur_range
            range_expansion = cur_range / avg_range5 if avg_range5 > 0 else 1.0

        # ── Group D: Index correlation ────────────────────────────
        directions      = self._last_directions
        dir_values      = list(directions.values())
        bullish_count   = sum(1 for d in dir_values if d == "BULLISH")
        bearish_count   = sum(1 for d in dir_values if d == "BEARISH")
        market_breadth  = bullish_count / len(dir_values) if dir_values else 0.5
        signal_dir_count = sum(1 for d in dir_values if d == consensus_direction)
        aligned_indices = signal_dir_count

        # ── Group E: OI & Futures ─────────────────────────────────
        futures_oi          = 0.0
        futures_oi_chg_pct  = 0.0
        atm_oi_ratio        = 1.0
        # Extended futures features — data-only, no gate
        # excess_basis_pct = raw_basis - theoretical_fair_value
        # fair value = spot × risk_free_rate × (dte / 365)
        # Raw basis at DTE=20 is ~0.35% just from fair value → not a signal.
        # Excess strips that out: +ve = institutional long bias, -ve = short/hedge bias.
        _RISK_FREE_RATE_PCT = config.RISK_FREE_RATE * 100  # convert 0.065 → 6.5
        excess_basis_pct    = 0.0
        futures_basis_slope = 0.0   # 5-candle slope of raw basis — DTE-neutral (slope of constant = 0)
        oi_regime           = -1    # -1=unknown, 0=long_buildup, 1=short_buildup,
                                    #              2=short_covering, 3=long_unwinding
        oi_regime_bullish   = 0     # 1 if price rising (long_buildup or short_covering)
        oi_regime_bearish   = 0     # 1 if price falling (short_buildup or long_unwinding)

        if futures_df is not None and len(futures_df) > 0 and "oi" in futures_df.columns:
            futures_oi = float(futures_df.iloc[-1]["oi"]) / 1_000_000  # in millions
            fut_price_now = float(futures_df.iloc[-1]["close"])

            # ── Excess basis: actual basis minus DTE-driven fair value ──
            # raw_basis_pct = (fut - spot) / spot * 100
            # fair_value_pct = risk_free_rate * dte / 365   (e.g. 6.5% * 20/365 = 0.356%)
            # excess = raw - fair_value: near-zero is neutral; +ve = longs, -ve = shorts
            if spot_price > 0 and fut_price_now > 0:
                raw_basis_pct    = (fut_price_now - spot_price) / spot_price * 100
                fair_value_pct   = _RISK_FREE_RATE_PCT * dte / 365.0
                excess_basis_pct = raw_basis_pct - fair_value_pct

            n5 = min(5, len(futures_df))
            if n5 >= 2:
                oi_now  = float(futures_df.iloc[-1]["oi"])
                oi_prev = float(futures_df.iloc[-n5]["oi"])
                futures_oi_chg_pct = ((oi_now - oi_prev) / oi_prev * 100) if oi_prev > 0 else 0.0

                # ── Basis slope: widening=institutional adding longs; narrowing=unwinding ─
                if df is not None and len(df) >= n5 and "close" in df.columns and spot_price > 0:
                    fut_prices  = futures_df["close"].iloc[-n5:].values.astype(float)
                    spot_prices = df["close"].iloc[-n5:].values.astype(float)
                    valid       = spot_prices > 0
                    if valid.sum() >= 2:
                        basis_series = np.where(valid,
                                                (fut_prices - spot_prices) / spot_prices * 100,
                                                0.0)
                        futures_basis_slope = float(
                            np.polyfit(range(len(basis_series)), basis_series, 1)[0]
                        )

                # ── Price-OI Regime ───────────────────────────────
                # Compares futures price + OI direction over last 5 candles.
                # long_buildup  (price↑ + OI↑): fresh longs → strong BULLISH confirmation
                # short_buildup (price↓ + OI↑): fresh shorts → strong BEARISH confirmation
                # short_covering(price↑ + OI↓): shorts closing → BULLISH but late/exhaustion
                # long_unwinding(price↓ + OI↓): longs closing → BEARISH but late/exhaustion
                price_up = fut_price_now > float(futures_df.iloc[-n5]["close"])
                oi_up    = (oi_now > oi_prev * 1.001) if oi_prev > 0 else False  # 0.1% noise floor
                if price_up and oi_up:
                    oi_regime = 0; oi_regime_bullish = 1   # long buildup
                elif not price_up and oi_up:
                    oi_regime = 1; oi_regime_bearish = 1   # short buildup
                elif price_up and not oi_up:
                    oi_regime = 2; oi_regime_bullish = 1   # short covering
                else:
                    oi_regime = 3; oi_regime_bearish = 1   # long unwinding

        if chain is not None and chain.atm_strike > 0:
            for strike in chain.strikes:
                if strike.strike == chain.atm_strike:
                    c_oi = float(strike.call_oi or 0)
                    p_oi = float(strike.put_oi or 0)
                    atm_oi_ratio = c_oi / p_oi if p_oi > 0 else 1.0
                    break

        # ── Group F: MTF ADX + DI slopes (for reversal ML learning) ─
        # Slope = linear regression gradient over last 5 candles.
        # Positive = DI rising, Negative = DI declining.
        # Key reversal pattern:
        #   BULLISH signal + minus_di_slope_5m/15m < 0 → bearish pressure fading
        #   BEARISH signal + plus_di_slope_5m/15m < 0  → bullish pressure fading
        # No gate — data collection only, ML learns the edge.
        adx_5m = 0.0; plus_di_5m = 0.0; minus_di_5m = 0.0
        adx_15m = 0.0
        plus_di_slope_5m = 0.0; minus_di_slope_5m = 0.0
        plus_di_slope_15m = 0.0; minus_di_slope_15m = 0.0
        di_reversal_5m = 0; di_reversal_15m = 0; di_reversal_both = 0

        def _di_slope(df_tf, col, n=5):
            """Linear regression slope of DI column over last n candles."""
            if df_tf is None or col not in df_tf.columns or len(df_tf) < 3:
                return 0.0
            vals = df_tf[col].iloc[-min(n, len(df_tf)):].values.astype(float)
            if len(vals) < 2:
                return 0.0
            return float(np.polyfit(range(len(vals)), vals, 1)[0])

        if df_5m is not None and len(df_5m) > 0:
            last5 = df_5m.iloc[-1]
            adx_5m           = float(last5.get("adx", 0))
            plus_di_5m       = float(last5.get("plus_di", 0))
            minus_di_5m      = float(last5.get("minus_di", 0))
            plus_di_slope_5m = _di_slope(df_5m, "plus_di")
            minus_di_slope_5m = _di_slope(df_5m, "minus_di")
        if df_15m is not None and len(df_15m) > 0:
            adx_15m            = float(df_15m.iloc[-1].get("adx", 0))
            plus_di_slope_15m  = _di_slope(df_15m, "plus_di")
            minus_di_slope_15m = _di_slope(df_15m, "minus_di")

        # Reversal flag: higher-TF opposing DI is declining = fading resistance
        if consensus_direction == "BULLISH":
            di_reversal_5m  = int(minus_di_slope_5m  < 0)
            di_reversal_15m = int(minus_di_slope_15m < 0)
        else:  # BEARISH
            di_reversal_5m  = int(plus_di_slope_5m  < 0)
            di_reversal_15m = int(plus_di_slope_15m < 0)
        di_reversal_both = int(di_reversal_5m == 1 and di_reversal_15m == 1)

        # ── Group G: Price Structure (5m + 15m HH/HL/LH/LL) ─────
        # Collected for ML learning only — NOT used as a gate.
        # Encodes: BULLISH=1, NEUTRAL=0, BEARISH=-1
        # aligned: 1 if structure matches consensus_direction, else 0
        _struct_enc = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
        struct_5m  = self._detect_structure(df_5m)
        struct_15m = self._detect_structure(df_15m)
        struct_5m_enc  = _struct_enc.get(struct_5m,  0)
        struct_15m_enc = _struct_enc.get(struct_15m, 0)
        struct_5m_aligned  = int(struct_5m  == consensus_direction)
        struct_15m_aligned = int(struct_15m == consensus_direction)
        struct_both_aligned = int(struct_5m == consensus_direction
                                  and struct_15m == consensus_direction)

        # ── Group H: VIX ─────────────────────────────────────────
        vix       = self._vix
        vix_high  = int(vix >= 15.0) if vix > 0 else 0

        # ── Group I: Historical performance context ───────────────
        # Both values are pre-computed in _run_evaluation and stored in raw_features.
        # _save_ml_features receives them via the raw_features['_context'] path,
        # or can be re-derived from the aggregator state here.
        # Using the aggregator state directly (same values that were stored in raw_features).
        setup_win_rate = 0.0
        try:
            _wr_map = self._db.get_rolling_setup_win_rates(index_name, lookback=20)
            if _wr_map:
                setup_win_rate = max(_wr_map.values())
        except Exception:
            pass

        mins_since_last_signal = 0.0
        _last_ts = self._last_trade_signal_time.get(index_name)
        if _last_ts:
            mins_since_last_signal = max(0.0, (timestamp - _last_ts).total_seconds() / 60.0)

        self._db.save_ml_features({
            "alert_id": alert_id,
            "index_name": index_name,
            "timestamp": timestamp,
            # Engine 1: Compression
            "atr": comp.features.get("atr_current", 0),
            "atr_pct_change": comp.features.get("atr_slope", 0),
            "compression_ratio": comp.features.get("range_ratio", 1),
            "candle_range_5": comp.features.get("recent_avg_range", 0),
            "candle_range_20": comp.features.get("avg_20_range", 0),
            # Engine 2: DI Momentum
            "plus_di": di.features.get("plus_di", 0),
            "minus_di": di.features.get("minus_di", 0),
            "adx": di.features.get("adx", 0),
            "di_spread": di.features.get("di_spread", 0),
            "plus_di_slope": di.features.get("spread_change", 0),
            # B6 fix: was hardcoded 0. Try feature names the DI engine may expose;
            # fall back to the negative of spread_change as a directional proxy.
            "minus_di_slope": di.features.get(
                "minus_di_change",
                di.features.get("minus_di_slope", -di.features.get("spread_change", 0))
            ),
            # Engine 3: Option Chain
            "pcr": oc.features.get("pcr", 0),
            "pcr_change": oc.features.get("pcr_change", 0),
            "call_oi_change": oc.features.get("call_oi_change", 0),
            "put_oi_change": oc.features.get("put_oi_change", 0),
            "iv_rank": oc.features.get("avg_call_iv", 0),
            "max_pain_distance": oc.features.get("max_pain_distance", 0),
            # Engine 4: Volume Pressure
            "volume_ratio": vol.features.get("volume_ratio", 1),
            "volume_ratio_5": vol.features.get("vol_5_mean_ratio", 1),
            "is_small_candle": vol.features.get("stealth_pattern", False),
            # Engine 5: Liquidity Trap
            "sweep_up": liq.sweep_up,
            "sweep_down": liq.sweep_down,
            "liq_wick_ratio": liq.features.get("wick_ratio_up", liq.features.get("wick_ratio_dn", 0)),
            "liq_volume_ratio": liq.features.get("volume_ratio", 1),
            # Engine 6: Gamma Levels
            "gamma_flip": gamma.gamma_flip,
            "near_gamma_wall": gamma.near_call_wall or gamma.near_put_wall,
            "dist_to_gamma_wall": gamma.features.get("dist_to_gamma_wall", 1),
            "dist_to_call_wall": gamma.features.get("dist_to_call_wall", 1),
            "dist_to_put_wall": gamma.features.get("dist_to_put_wall", 1),
            # Engine 7: IV Expansion
            "iv_expanding": iv.iv_expanding,
            "iv_skew_ratio": iv.features.get("iv_skew_ratio", 1.0),
            "avg_atm_iv": iv.features.get("avg_atm_iv", 0),
            "iv_change_pct": iv.features.get("iv_change_pct", 0),
            # Engine 9: VWAP Pressure
            "vwap":             vwap.features.get("vwap", 0) if vwap else 0,
            "dist_to_vwap_pct": vwap.features.get("dist_to_vwap_pct", 0) if vwap else 0,
            "vwap_cross_up":    vwap.features.get("vwap_cross_up", False) if vwap else False,
            "vwap_cross_down":  vwap.features.get("vwap_cross_down", False) if vwap else False,
            "vwap_bounce":      vwap.features.get("vwap_bounce", False) if vwap else False,
            "vwap_rejection":   vwap.features.get("vwap_rejection", False) if vwap else False,
            "vwap_vol_ratio":   vwap.features.get("vwap_vol_ratio", 0) if vwap else 0,
            # Engine 8: Market Regime
            "market_regime": regime.regime,
            "regime_adx": regime.features.get("adx", 0),
            "regime_atr_ratio": regime.features.get("atr_ratio", 1),
            # Trigger flags
            "compression_triggered": comp.is_triggered,
            "di_triggered": di.is_triggered,
            "option_chain_triggered": oc.is_triggered,
            "volume_triggered": vol.is_triggered,
            "liquidity_trap_triggered": liq.is_triggered,
            "gamma_triggered": gamma.is_triggered,
            "iv_triggered": iv.is_triggered,
            "regime_triggered": regime.is_triggered,
            "vwap_triggered": vwap.is_triggered if vwap else False,
            "engines_count": engines_count,
            "candle_completion_pct": candle_completion_pct,
            # Group A: Time context
            "mins_since_open": mins_since_open,
            "session": session,
            "is_expiry": _is_expiry,
            "day_of_week": day_of_week,
            "dte": dte,
            # Group B: Price context
            "spot_vs_prev_pct": spot_vs_prev_pct,
            "atr_pct_spot": atr_pct_spot,
            "chop": chop_val,
            "efficiency_ratio": er_val,
            "gap_pct": gap_pct,
            "preopen_gap_pct": preopen_gap_pct,
            # Group C: Candle patterns
            "prev_body_ratio": prev_body_ratio,
            "prev_bullish": prev_bullish,
            "consec_bull": consec_bull,
            "consec_bear": consec_bear,
            "range_expansion": range_expansion,
            # Group D: Index correlation
            "aligned_indices": aligned_indices,
            "market_breadth": market_breadth,
            # Group E: OI & Futures
            "futures_oi_m":        futures_oi,
            "futures_oi_chg_pct":  futures_oi_chg_pct,
            "atm_oi_ratio":        atm_oi_ratio,
            # Extended futures — institutional footprint (data-only, no gate)
            "excess_basis_pct":    round(excess_basis_pct,    4),
            "futures_basis_slope": round(futures_basis_slope, 4),
            "oi_regime":           oi_regime,
            "oi_regime_bullish":   oi_regime_bullish,
            "oi_regime_bearish":   oi_regime_bearish,
            # Group F: MTF ADX + DI slopes (reversal learning — no gate)
            "adx_5m": adx_5m,
            "plus_di_5m": plus_di_5m,
            "minus_di_5m": minus_di_5m,
            "adx_15m": adx_15m,
            "plus_di_slope_5m":  round(plus_di_slope_5m,  3),
            "minus_di_slope_5m": round(minus_di_slope_5m, 3),
            "plus_di_slope_15m":  round(plus_di_slope_15m,  3),
            "minus_di_slope_15m": round(minus_di_slope_15m, 3),
            "di_reversal_5m":   di_reversal_5m,
            "di_reversal_15m":  di_reversal_15m,
            "di_reversal_both": di_reversal_both,
            # Group G: Price Structure (5m + 15m HH/HL/LH/LL) — ML only, no gate
            "struct_5m":          struct_5m_enc,
            "struct_15m":         struct_15m_enc,
            "struct_5m_aligned":  struct_5m_aligned,
            "struct_15m_aligned": struct_15m_aligned,
            "struct_both_aligned": struct_both_aligned,
            # Group H: VIX
            "vix": vix,
            "vix_high": vix_high,
            # Group I: Signal identity
            "direction_encoded": 1 if consensus_direction == "BULLISH" else -1,
            "index_encoded": self._INDEX_ENCODING.get(index_name, 4),
            "is_trade_signal": is_trade_signal,
            # Group J: Historical performance context
            "setup_win_rate":          round(setup_win_rate, 1),
            "mins_since_last_signal":  round(mins_since_last_signal, 1),
            "label": -1,  # Unlabeled — auto_labeler assigns later
            "label_direction": 0,
        })
