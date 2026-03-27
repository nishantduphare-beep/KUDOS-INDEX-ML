"""
engines/s11_monitor.py
─────────────────────────────────────────────────────────────────
S11 Setup Monitor — standalone paper-trade system.

S11 condition (both BULLISH and BEARISH sides tracked):
  • DI aligned    : plus_di > minus_di (BULL) / minus_di > plus_di (BEAR)
  • TRENDING regime: market_regime == "TRENDING"
  • Volume surge  : volume_ratio >= 1.5

This class is registered as a UI callback with AlertManager.  Every
time an alert fires, on_alert() is called — it reads raw_features
that were already computed by SignalAggregator (zero duplicate work).

For each CONFIRMED S11 TradeSignal it:
  1. Opens a paper position in s11_paper_trades DB table (2 lots)
  2. Tracks levels every engine tick via tick()
  3. After T2 hit — trails SL to entry price (breakeven)
  4. Closes on SL / T3 / EOD and records realized P&L

Sound gating (Option A):
  Sets alert_obj.is_s11 = True.  AlertManager._dispatch() fires sound
  ONLY when is_s11 is True — all other signals go silent.

EOD close logic (15:30 IST):
  T1 was hit → WIN (partial, 50% booked at T1)
  T1 not hit → NEUTRAL

P&L formulas (2 lots, option premium):
  units = 2 × lot_size
  SL before T2 → LOSS:   pnl = (sl_price   - entry_price) × units   [negative]
  T2 hit, then SL → WIN: pnl = (t2_price    - entry_price) × units × 0.5
  T3 hit          → WIN: pnl = (t3_price    - entry_price) × units
  EOD WIN (T1 hit)→ WIN: pnl = (exit_price  - entry_price) × units × 0.5
  EOD NEUTRAL     → NTL: pnl = (exit_price  - entry_price) × units
"""

import logging
import threading
from datetime import datetime, time as _time
from typing import Dict, List, Optional, Callable

import config
from database.manager import DatabaseManager

logger = logging.getLogger(__name__)
_IST = config.IST

# S11 condition thresholds
_S11_VOLUME_RATIO_MIN = 1.5
_S11_REGIME_REQUIRED  = "TRENDING"

# Level tracking key prefix
_EOD_TIME = _time(15, 30)


class S11Monitor:
    """
    Monitors S11 setup, manages paper positions, provides data for S11Tab.

    Lifecycle:
        __init__()          — load OPEN trades from DB (rehydrate)
        on_alert(alert)     — called by AlertManager for every alert
        tick(spots, ltps)   — called every 5 s by engine loop
        eod_close(spots)    — called at 15:30 to close all open positions

    Public query (thread-safe):
        get_early_alerts_today()
        get_open_positions()
        get_closed_today()
        get_stats()
    """

    def __init__(
        self,
        db: DatabaseManager,
        on_s11_open:  Optional[Callable[[dict], None]] = None,
        on_s11_close: Optional[Callable[[dict], None]] = None,
    ):
        """
        db            — DatabaseManager singleton
        on_s11_open   — optional UI callback(state_dict) fired when a new paper
                        position is opened — used by S11Tab to refresh its table
        on_s11_close  — optional UI callback(state_dict) fired when a paper
                        position closes — used by S11Tab to move it to closed list
        """
        self._db          = db
        self._on_open     = on_s11_open
        self._on_close    = on_s11_close
        self._lock        = threading.Lock()

        # {trade_id: state_dict} — live paper positions
        self._open: Dict[int, dict] = {}

        # Early alert log for today's tab (capped at 200)
        self._early_alerts: List[dict] = []

        # Closed trades today
        self._closed_today: List[dict] = []

        # Dedup — prevent double-entry on the same 3-min candle
        self._seen_early:     set = set()   # (index, direction, candle_min)
        self._seen_confirmed: set = set()   # (index, direction, candle_min)

        self._rehydrate()

    # ─── S11 Condition ────────────────────────────────────────────

    @staticmethod
    def _is_s11(raw: dict, direction: str) -> bool:
        """
        Returns True if raw_features satisfy S11 condition for direction.

        raw_features is a nested dict from SignalAggregator:
          raw["market_regime"]   = regime_r.features   (dict)
          raw["volume_pressure"] = vol_r.features       (dict)
          raw["di_momentum"]     = di_r.features        (dict)

        TRENDING regime: MarketRegimeDetector writes "trend_strength" into
        features ONLY when regime == TRENDING — so its presence is the flag.
        DI aligned: plus_di > minus_di (BULL) or minus_di > plus_di (BEAR)
        Volume    : volume_ratio >= 1.5
        """
        regime_f = raw.get("market_regime", {}) or {}
        # trend_strength key is written only when regime is TRENDING
        if "trend_strength" not in regime_f:
            return False

        vol_f        = raw.get("volume_pressure", {}) or {}
        volume_ratio = float(vol_f.get("volume_ratio", 0) or 0)
        if volume_ratio < _S11_VOLUME_RATIO_MIN:
            return False

        di_f     = raw.get("di_momentum", {}) or {}
        plus_di  = float(di_f.get("plus_di",  0) or 0)
        minus_di = float(di_f.get("minus_di", 0) or 0)

        if direction == "BULLISH":
            return plus_di > minus_di
        elif direction == "BEARISH":
            return minus_di > plus_di
        return False

    # ─── Alert Callback ───────────────────────────────────────────

    def on_alert(self, alert_obj) -> None:
        """
        Registered with AlertManager as a UI callback.
        Called for every EarlyMoveAlert and TradeSignal before sound fires.

        Sets alert_obj.is_s11 = True when S11 condition is met.
        Opens a paper position for confirmed TradeSignals only.
        """
        raw = getattr(alert_obj, "raw_features", {}) or {}
        direction = getattr(alert_obj, "direction", "")
        if not self._is_s11(raw, direction):
            return

        # Tag the alert — AlertManager uses this for sound gating
        alert_obj.is_s11 = True

        alert_type  = getattr(alert_obj, "alert_type",  "EARLY_MOVE")
        is_confirmed = getattr(alert_obj, "is_confirmed", False)

        # ── Early Move Alerts ─────────────────────────────────────
        if alert_type == "EARLY_MOVE":
            ts      = getattr(alert_obj, "timestamp", datetime.now())
            cm      = _candle_min(ts)
            key     = (getattr(alert_obj, "index_name", ""), direction, cm)
            with self._lock:
                if key not in self._seen_early:
                    self._seen_early.add(key)
                    entry = {
                        "type":             "EARLY_MOVE",
                        "index_name":       getattr(alert_obj, "index_name", ""),
                        "direction":        direction,
                        "timestamp":        ts,
                        "confidence_score": getattr(alert_obj, "confidence_score", 0.0),
                        "spot_price":       getattr(alert_obj, "spot_price", 0.0),
                        "engines":          getattr(alert_obj, "engines_triggered", []),
                    }
                    self._early_alerts.append(entry)
                    if len(self._early_alerts) > 200:
                        self._early_alerts = self._early_alerts[-200:]
            logger.info(
                f"S11 EARLY [{getattr(alert_obj,'index_name','')}] "
                f"{direction} spot={getattr(alert_obj,'spot_price',0):.0f}"
            )

        # ── Confirmed Trade Signal → open paper position ──────────
        # main_window sets alert_type="CONFIRMED_SIGNAL" and is_confirmed=True
        elif is_confirmed:
            ts  = getattr(alert_obj, "timestamp", datetime.now())
            cm  = _candle_min(ts)
            key = (getattr(alert_obj, "index_name", ""), direction, cm)
            with self._lock:
                already = key in self._seen_confirmed
            if not already:
                with self._lock:
                    self._seen_confirmed.add(key)
                self._open_paper(alert_obj)

    # ─── Paper Position Open ──────────────────────────────────────

    def _open_paper(self, signal) -> None:
        """Create a new S11 paper position from a confirmed TradeSignal."""
        index   = signal.index_name
        bull    = (signal.direction == "BULLISH")
        atr     = signal.atr or 1.0
        spot    = signal.spot_price

        # Spot-level targets (used for tracking and display)
        sl_m = config.OUTCOME_SL_ATR_MULT
        t1_m = config.OUTCOME_T1_ATR_MULT
        t2_m = config.OUTCOME_T2_ATR_MULT
        t3_m = config.OUTCOME_T3_ATR_MULT

        if bull:
            spot_sl = spot - atr * sl_m
            spot_t1 = spot + atr * t1_m
            spot_t2 = spot + atr * t2_m
            spot_t3 = spot + atr * t3_m
        else:
            spot_sl = spot + atr * sl_m
            spot_t1 = spot - atr * t1_m
            spot_t2 = spot - atr * t2_m
            spot_t3 = spot - atr * t3_m

        # Option premium levels from signal
        entry_price = float(getattr(signal, "entry_reference",    0) or 0)
        sl_price    = float(getattr(signal, "stop_loss_reference", 0) or 0)
        t1_price    = float(getattr(signal, "target1",  0) or 0)
        t2_price    = float(getattr(signal, "target2",  0) or 0)
        t3_price    = float(getattr(signal, "target3",  0) or 0)

        lot_size    = config.SYMBOL_MAP.get(index, {}).get("lot_size", 1)
        lots        = 2
        units       = lots * lot_size

        # Pre-computed P&L at each level
        pnl_at_sl  = round((sl_price  - entry_price) * units, 2) if entry_price and sl_price  else 0.0
        pnl_at_t1  = round((t1_price  - entry_price) * units, 2) if entry_price and t1_price  else 0.0
        pnl_at_t2  = round((t2_price  - entry_price) * units, 2) if entry_price and t2_price  else 0.0
        pnl_at_t3  = round((t3_price  - entry_price) * units, 2) if entry_price and t3_price  else 0.0

        today_str   = signal.timestamp.strftime("%Y-%m-%d")
        instrument  = getattr(signal, "suggested_instrument", "") or ""
        strike      = float(getattr(signal, "strike",      0) or 0)
        option_type = getattr(signal, "option_type", "") or ""
        alert_id    = getattr(signal, "alert_id", 0) or 0
        conf_score  = getattr(signal, "confidence_score", 0.0) or 0.0

        # Derive option chain lookup key (same format as OutcomeTracker)
        opt_key = (f"{index}:{int(strike)}:{option_type}"
                   if strike and option_type else None)

        db_data = {
            "alert_id":        alert_id,
            "index_name":      index,
            "direction":       signal.direction,
            "confidence_score": conf_score,
            "date":            today_str,
            "entry_time":      signal.timestamp,
            "entry_spot":      spot,
            "entry_price":     entry_price,
            "instrument":      instrument,
            "strike":          strike,
            "option_type":     option_type,
            "atr_at_signal":   atr,
            "lot_size":        lot_size,
            "lots":            lots,
            "units":           units,
            "sl_price":        sl_price,
            "t1_price":        t1_price,
            "t2_price":        t2_price,
            "t3_price":        t3_price,
            "spot_sl":         round(spot_sl, 2),
            "spot_t1":         round(spot_t1, 2),
            "spot_t2":         round(spot_t2, 2),
            "spot_t3":         round(spot_t3, 2),
            "pnl_at_sl":       pnl_at_sl,
            "pnl_at_t1":       pnl_at_t1,
            "pnl_at_t2":       pnl_at_t2,
            "pnl_at_t3":       pnl_at_t3,
            "t1_hit":          False,
            "t2_hit":          False,
            "t3_hit":          False,
            "sl_hit":          False,
            "mfe_atr":         0.0,
            "mae_atr":         0.0,
            "status":          "OPEN",
            "created_at":      datetime.utcnow(),
        }

        try:
            trade_id = self._db.save_s11_paper_trade(db_data)
        except Exception as exc:
            logger.error(f"S11Monitor: DB save failed: {exc}")
            return

        state = {
            "trade_id":    trade_id,
            "alert_id":    alert_id,
            "index_name":  index,
            "direction":   signal.direction,
            "entry_time":  signal.timestamp,
            "entry_spot":  spot,
            "entry_price": entry_price,
            "atr":         atr,
            # Spot levels for detection
            "spot_sl":     spot_sl,
            "spot_t1":     spot_t1,
            "spot_t2":     spot_t2,
            "spot_t3":     spot_t3,
            # Option premium levels for P&L display
            "sl_price":    sl_price,
            "t1_price":    t1_price,
            "t2_price":    t2_price,
            "t3_price":    t3_price,
            # Dynamic SL (trails to breakeven after T2)
            "current_sl":  spot_sl,
            # Level hit state
            "t1_hit":      False,
            "t2_hit":      False,
            "t3_hit":      False,
            # Option chain key for live LTP
            "opt_key":     opt_key,
            # Sizing
            "lot_size":    lot_size,
            "lots":        lots,
            "units":       units,
            # Excursion
            "mfe_atr":     0.0,
            "mae_atr":     0.0,
            # Pre-computed P&L
            "pnl_at_sl":   pnl_at_sl,
            "pnl_at_t1":   pnl_at_t1,
            "pnl_at_t2":   pnl_at_t2,
            "pnl_at_t3":   pnl_at_t3,
        }

        with self._lock:
            self._open[trade_id] = state

        logger.info(
            f"S11 PAPER OPEN [{index}] {signal.direction} "
            f"entry_spot={spot:.0f} SL={spot_sl:.0f} "
            f"T1={spot_t1:.0f} T2={spot_t2:.0f} T3={spot_t3:.0f} "
            f"units={units} [trade_id={trade_id}]"
        )

        if self._on_open:
            try:
                self._on_open(dict(state))
            except Exception as exc:
                logger.warning(f"S11Monitor on_open callback: {exc}")

    # ─── Tick ─────────────────────────────────────────────────────

    def tick(
        self,
        spot_prices: Dict[str, float],
        option_ltps: Optional[Dict[str, float]] = None,
    ) -> List[int]:
        """
        Called every engine cycle (~5 s).
        Checks all open S11 paper positions against current spot/LTP.
        Returns list of trade_ids closed this tick.
        """
        now     = datetime.now(_IST).replace(tzinfo=None)
        is_eod  = now.time() >= _EOD_TIME
        closed: List[int] = []
        opt_ltps = option_ltps or {}

        with self._lock:
            for trade_id, state in list(self._open.items()):
                spot = spot_prices.get(state["index_name"])
                if spot is None or spot <= 0:
                    continue

                opt_key   = state.get("opt_key", "")
                opt_price = opt_ltps.get(opt_key) if opt_key else None

                self._update_excursion(state, spot)

                if is_eod:
                    self._close_paper(
                        trade_id, state, spot, "EOD",
                        exit_price=opt_price or 0.0,
                        exit_spot=spot, now=now,
                    )
                    closed.append(trade_id)
                    continue

                done, reason = self._check_levels(state, spot, now, opt_price)
                if done:
                    self._close_paper(
                        trade_id, state, spot, reason,
                        exit_price=opt_price or 0.0,
                        exit_spot=spot, now=now,
                    )
                    closed.append(trade_id)

        return closed

    # ─── Level Checks ─────────────────────────────────────────────

    def _check_levels(
        self, state: dict, spot: float, now: datetime,
        opt_price: Optional[float] = None,
    ):
        """
        Returns (done: bool, reason: str).
        Mutates state for t1_hit / t2_hit and current_sl trail.
        All level detection is on SPOT price.
        Stores actual option LTP (opt_price) at T1/T2 hit time for real P&L.
        """
        bull = (state["direction"] == "BULLISH")

        # T3 → close WIN
        t3_spot = state["spot_t3"]
        if (bull and spot >= t3_spot) or (not bull and spot <= t3_spot):
            if not state["t3_hit"]:
                state["t3_hit"] = True
                try:
                    self._db.update_s11_paper_trade(state["trade_id"], {
                        "t3_hit": True, "t3_hit_time": now,
                    })
                except Exception:
                    pass
            return True, "T3"

        # T2 → milestone + trail SL to breakeven + capture live LTP
        t2_spot = state["spot_t2"]
        if (bull and spot >= t2_spot) or (not bull and spot <= t2_spot):
            if not state["t2_hit"]:
                state["t2_hit"]          = True
                state["current_sl"]      = state["entry_spot"]   # trail to breakeven
                # Store actual option LTP at T2 — used for real P&L on SL-after-T2
                if opt_price and opt_price > 0:
                    state["t2_actual_ltp"] = opt_price
                try:
                    self._db.update_s11_paper_trade(state["trade_id"], {
                        "t2_hit": True, "t2_hit_time": now,
                    })
                except Exception:
                    pass
                logger.info(
                    f"S11 T2 hit [{state['index_name']}] {state['direction']} "
                    f"spot={spot:.0f} opt={opt_price or 0:.2f} "
                    f"— SL trailed to entry {state['entry_spot']:.0f}"
                )

        # T1 → milestone + capture live LTP
        t1_spot = state["spot_t1"]
        if (bull and spot >= t1_spot) or (not bull and spot <= t1_spot):
            if not state["t1_hit"]:
                state["t1_hit"] = True
                # Store actual option LTP at T1 — used for real P&L on EOD-after-T1
                if opt_price and opt_price > 0:
                    state["t1_actual_ltp"] = opt_price
                try:
                    self._db.update_s11_paper_trade(state["trade_id"], {
                        "t1_hit": True, "t1_hit_time": now,
                    })
                except Exception:
                    pass

        # SL hit (uses current_sl which may have trailed to breakeven)
        cur_sl = state["current_sl"]
        if (bull and spot <= cur_sl) or (not bull and spot >= cur_sl):
            return True, "SL"

        return False, ""

    # ─── Excursion ────────────────────────────────────────────────

    def _update_excursion(self, state: dict, spot: float) -> None:
        """Update MFE/MAE in ATR units."""
        atr  = state["atr"] or 1.0
        bull = (state["direction"] == "BULLISH")
        move = (spot - state["entry_spot"]) if bull else (state["entry_spot"] - spot)
        mfe  = move / atr if move > 0 else 0.0
        mae  = (-move / atr) if move < 0 else 0.0
        if mfe > state["mfe_atr"]:
            state["mfe_atr"] = round(mfe, 3)
        if mae > state["mae_atr"]:
            state["mae_atr"] = round(mae, 3)

    # ─── Paper Position Close ─────────────────────────────────────

    def _close_paper(
        self,
        trade_id: int,
        state: dict,
        exit_spot: float,
        reason: str,
        exit_price: float,
        now: datetime,
    ) -> None:
        """
        Close a paper position using ACTUAL live option LTPs wherever available.
        Falls back to pre-computed signal levels only when live LTP is missing.

        P&L formulas (units = 2 × lot_size):
          T3              → WIN:     (exit_price       − entry) × units
          SL, T2 was hit  → WIN:     (t2_actual_ltp    − entry) × units × 0.5
                                   + (exit_price       − entry) × units × 0.5
          SL, no T2       → LOSS:    (exit_price       − entry) × units
          EOD, T1 was hit → WIN:     (t1_actual_ltp    − entry) × units × 0.5
                                   + (exit_price       − entry) × units × 0.5
          EOD, no T1      → NEUTRAL: (exit_price       − entry) × units

        exit_price is always the live option LTP at the close moment.
        t1/t2_actual_ltp are captured when each spot level is first touched.
        If live LTP was unavailable at that moment, pre-computed levels are used.
        """
        ep     = state["entry_price"]
        units  = state["units"]
        t2_hit = state["t2_hit"]
        t1_hit = state["t1_hit"]

        # Real LTPs captured at milestone touches (may fall back to signal levels)
        t1_ltp = state.get("t1_actual_ltp") or state["t1_price"]
        t2_ltp = state.get("t2_actual_ltp") or state["t2_price"]

        if reason == "T3":
            outcome = "WIN"
            # exit_price = live LTP at the moment T3 spot level was hit
            pnl = round((exit_price - ep) * units, 2) if ep > 0 else 0.0

        elif reason == "SL":
            if t2_hit:
                # 50% booked at T2 (t2_ltp), 50% exits now at exit_price
                outcome = "WIN"
                pnl = (
                    round((t2_ltp    - ep) * units * 0.5, 2)
                  + round((exit_price - ep) * units * 0.5, 2)
                ) if ep > 0 else 0.0
            else:
                # Full loss — exit_price = live LTP at SL spot level hit
                outcome = "LOSS"
                pnl = round((exit_price - ep) * units, 2) if ep > 0 else 0.0

        elif reason == "EOD":
            if t1_hit:
                # 50% booked at T1 (t1_ltp), 50% exits at EOD LTP
                outcome = "WIN"
                pnl = (
                    round((t1_ltp    - ep) * units * 0.5, 2)
                  + round((exit_price - ep) * units * 0.5, 2)
                ) if ep > 0 else 0.0
            else:
                outcome = "NEUTRAL"
                pnl = round((exit_price - ep) * units, 2) if ep > 0 else 0.0

        else:
            outcome = "NEUTRAL"
            pnl = 0.0

        try:
            self._db.update_s11_paper_trade(trade_id, {
                "status":       "CLOSED",
                "exit_time":    now,
                "exit_price":   round(exit_price, 2),
                "exit_spot":    round(exit_spot, 2),
                "exit_reason":  reason,
                "outcome":      outcome,
                "realized_pnl": pnl,
                "mfe_atr":      state["mfe_atr"],
                "mae_atr":      state["mae_atr"],
                "t1_hit":       state["t1_hit"],
                "t2_hit":       state["t2_hit"],
                "sl_hit":       reason == "SL",
            })
        except Exception as exc:
            logger.error(f"S11Monitor: DB close failed for {trade_id}: {exc}")

        closed_rec = {
            **state,
            "exit_reason":  reason,
            "outcome":      outcome,
            "realized_pnl": pnl,
            "exit_price":   exit_price,
            "exit_spot":    exit_spot,
        }
        self._closed_today.append(closed_rec)

        # Remove from open dict (caller iterates over a snapshot so safe to mutate here)
        self._open.pop(trade_id, None)

        logger.info(
            f"S11 PAPER CLOSE [{state['index_name']}] {state['direction']} "
            f"reason={reason} outcome={outcome} pnl=₹{pnl:+.0f} "
            f"[trade_id={trade_id}]"
        )

        if self._on_close:
            try:
                self._on_close(dict(closed_rec))
            except Exception as exc:
                logger.warning(f"S11Monitor on_close callback: {exc}")

    # ─── Public Query API ─────────────────────────────────────────

    def get_early_alerts_today(self) -> List[dict]:
        """Thread-safe snapshot of today's early alerts."""
        with self._lock:
            return list(self._early_alerts)

    def get_open_positions(self) -> List[dict]:
        """Thread-safe snapshot of open paper positions."""
        with self._lock:
            return [dict(v) for v in self._open.values()]

    def get_closed_today(self) -> List[dict]:
        """Thread-safe snapshot of closed paper positions today."""
        with self._lock:
            return list(self._closed_today)

    def get_stats(self) -> dict:
        """Return aggregate stats from the DB for the S11 tab header."""
        try:
            return self._db.get_s11_stats()
        except Exception as exc:
            logger.warning(f"S11Monitor.get_stats: {exc}")
            return {
                "total": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_pnl": 0.0,
                "t1_rate": 0.0, "t2_rate": 0.0, "t3_rate": 0.0,
            }

    # ─── Rehydrate (startup) ──────────────────────────────────────

    def _rehydrate(self) -> None:
        """
        Re-load OPEN s11_paper_trades from the DB on startup.
        Allows session continuity if the app restarts mid-day.
        """
        try:
            open_rows = self._db.get_open_s11_trades()
        except Exception as exc:
            logger.warning(f"S11Monitor rehydrate: {exc}")
            return

        for row in open_rows:
            bull = (row.direction == "BULLISH")
            # Restore state dict from ORM row
            state = {
                "trade_id":    row.id,
                "alert_id":    row.alert_id or 0,
                "index_name":  row.index_name,
                "direction":   row.direction,
                "entry_time":  row.entry_time,
                "entry_spot":  row.entry_spot,
                "entry_price": row.entry_price,
                "atr":         row.atr_at_signal or 1.0,
                "spot_sl":     row.spot_sl,
                "spot_t1":     row.spot_t1,
                "spot_t2":     row.spot_t2,
                "spot_t3":     row.spot_t3,
                "sl_price":    row.sl_price,
                "t1_price":    row.t1_price,
                "t2_price":    row.t2_price,
                "t3_price":    row.t3_price,
                "current_sl":  row.entry_spot if row.t2_hit else row.spot_sl,
                "t1_hit":      bool(row.t1_hit),
                "t2_hit":      bool(row.t2_hit),
                "t3_hit":      bool(row.t3_hit) if row.t3_hit is not None else False,
                "opt_key":     (f"{row.index_name}:{int(row.strike)}:{row.option_type}"
                                if row.strike and row.option_type else None),
                "lot_size":    row.lot_size,
                "lots":        row.lots,
                "units":       row.units,
                "mfe_atr":     row.mfe_atr or 0.0,
                "mae_atr":     row.mae_atr or 0.0,
                "pnl_at_sl":   row.pnl_at_sl,
                "pnl_at_t1":   row.pnl_at_t1,
                "pnl_at_t2":   row.pnl_at_t2,
                "pnl_at_t3":   row.pnl_at_t3,
            }
            self._open[row.id] = state

            # Rebuild dedup key so we don't re-open on the same candle
            cm  = _candle_min(row.entry_time)
            key = (row.index_name, row.direction, cm)
            self._seen_confirmed.add(key)

        if open_rows:
            logger.info(f"S11Monitor: rehydrated {len(open_rows)} open position(s)")

    # ─── EOD helper ───────────────────────────────────────────────

    def eod_close_all(self, spot_prices: Dict[str, float]) -> None:
        """
        Force-close all remaining open positions at EOD (15:30).
        Called from main_window when the market closes.
        Wraps tick() with is_eod forced True by passing 15:31 internally —
        easier to just call tick() after 15:30 since it auto-detects EOD.
        """
        self.tick(spot_prices)


# ─── Helpers ─────────────────────────────────────────────────────

def _candle_min(ts: datetime) -> int:
    """Return 3-minute candle bucket index for a timestamp."""
    return (ts.hour * 60 + ts.minute) // 3
