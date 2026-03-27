"""
ml/outcome_tracker.py
─────────────────────────────────────────────────────────────────
Two-phase trade lifecycle:

  PHASE 1 — OPEN tracking (entry → SL/T3/EOD close)
    Every engine tick (5 s):
      • Check spot vs SL / T1 / T2 / T3 levels
      • Update MFE / MAE continuously
      • SL hit  → close as LOSS, move to phase 2
      • T3 hit  → close as WIN,  move to phase 2
      • T1/T2   → milestone recorded, stay in phase 1
      • 15:30   → EOD close all remaining open

  PHASE 2 — POST-CLOSE monitoring (trade closed → 15:30 EOD)
    Every engine tick, for already-closed trades:
      • Continue tracking price against the SAME SL/T1/T2/T3 levels
      • Records: did price recover to T1/T2/T3 after SL hit?
      •          what was the MFE/MAE for the rest of the day?
      • At 15:30: write post_close_eod_spot + all post-close hit flags to DB

  This answers the critical ML question:
    "SL was hit at 10:30 — but price hit T3 by 12:00. SL was too tight."

  On startup:
    • Re-hydrate OPEN outcomes from a prior session

Outcome data feeds back into MLFeatureRecord for richer model training.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone, time as _time
from typing import Dict, List, Optional, Callable

import config
from database.manager import DatabaseManager

logger = logging.getLogger(__name__)

_IST = config.IST


class OutcomeTracker:
    """
    Tracks all open TRADE_SIGNAL outcomes against live spot prices.

    Usage:
        tracker = OutcomeTracker(db)
        tracker.register(signal, alert_id)           # when a signal fires
        closed_ids = tracker.tick({"NIFTY": 23500})  # every engine tick
    """

    def __init__(
        self,
        db: DatabaseManager,
        on_close: Optional[Callable[[int, str], None]] = None,
    ):
        """
        db        — DatabaseManager singleton
        on_close  — optional callback(outcome_id, outcome_str) called when a
                    trade closes; used by main_window to emit UI signals
        """
        self._db       = db
        self._on_close = on_close
        self._lock     = threading.Lock()
        # Phase 1: open trades being tracked  {outcome_id: state_dict}
        self._open: Dict[int, dict] = {}
        # Phase 2: closed trades still monitored until EOD {outcome_id: pc_state_dict}
        self._post_close: Dict[int, dict] = {}
        # Layer 2 LTP cache — last known good price per opt_key
        # Used when option chain fetch fails for a tick (network hiccup)
        # Format: {opt_key: (ltp, timestamp)}
        self._ltp_cache: Dict[str, tuple] = {}
        self._LTP_CACHE_MAX_AGE_SEC = 30   # stale after 30 seconds
        self._rehydrate()

    # ─── Public API ───────────────────────────────────────────────

    def get_open_states(self) -> Dict[int, dict]:
        """
        Return a thread-safe snapshot of the currently open trade states.
        Each value is a copy of the state dict keyed by outcome_id.
        Used by OrderManager for paper P&L updates without accessing _lock directly.
        """
        with self._lock:
            return {k: dict(v) for k, v in self._open.items()}

    def register(self, signal, alert_id: int) -> int:
        """
        Called immediately after a TRADE_SIGNAL fires.
        Computes spot-level SL/T1/T2/T3 from ATR (kept for reference/post-close).
        Primary tracking uses the OPTION PREMIUM levels from the signal.
        Inserts a TradeOutcome DB row with status=OPEN.
        Returns the new outcome_id.
        """
        atr   = signal.atr or 1.0
        spot  = signal.spot_price
        bull  = (signal.direction == "BULLISH")

        # Spot-based levels — kept for reference and post-close spot tracking
        if bull:
            sl = spot - atr * config.OUTCOME_SL_ATR_MULT
            t1 = spot + atr * config.OUTCOME_T1_ATR_MULT
            t2 = spot + atr * config.OUTCOME_T2_ATR_MULT
            t3 = spot + atr * config.OUTCOME_T3_ATR_MULT
        else:
            sl = spot + atr * config.OUTCOME_SL_ATR_MULT
            t1 = spot - atr * config.OUTCOME_T1_ATR_MULT
            t2 = spot - atr * config.OUTCOME_T2_ATR_MULT
            t3 = spot - atr * config.OUTCOME_T3_ATR_MULT

        # Option premium levels — primary tracking basis
        entry_price    = getattr(signal, "entry_reference",    0.0) or 0.0
        stop_loss_opt  = getattr(signal, "stop_loss_reference", 0.0) or 0.0
        t1_opt         = getattr(signal, "target1",  0.0) or 0.0
        t2_opt         = getattr(signal, "target2",  0.0) or 0.0
        t3_opt         = getattr(signal, "target3",  0.0) or 0.0
        strike         = float(getattr(signal, "strike", 0) or 0)
        option_type    = getattr(signal, "option_type", "") or ""

        # Key to look up live LTP in the option chain every tick
        # format: "MIDCPNIFTY:2675:PE"
        opt_key = (f"{signal.index_name}:{int(strike)}:{option_type}"
                   if strike and option_type else None)

        # Rupee P&L pre-computation — use lot size from config
        lot_size = config.SYMBOL_MAP.get(signal.index_name, {}).get("lot_size", 1)
        investment_amt = round(entry_price * lot_size, 2) if entry_price > 0 else 0.0
        pnl_sl = round((stop_loss_opt  - entry_price) * lot_size, 2) if entry_price > 0 and stop_loss_opt  > 0 else 0.0
        pnl_t1 = round((t1_opt         - entry_price) * lot_size, 2) if entry_price > 0 and t1_opt         > 0 else 0.0
        pnl_t2 = round((t2_opt         - entry_price) * lot_size, 2) if entry_price > 0 and t2_opt         > 0 else 0.0
        pnl_t3 = round((t3_opt         - entry_price) * lot_size, 2) if entry_price > 0 and t3_opt         > 0 else 0.0

        outcome_id = self._db.save_trade_outcome({
            "alert_id":      alert_id,
            "alert_type":    getattr(signal, "alert_type", "TRADE_SIGNAL"),
            "index_name":    signal.index_name,
            "instrument":    getattr(signal, "suggested_instrument", ""),
            "direction":     signal.direction,
            "entry_time":    signal.timestamp,
            "entry_spot":    spot,
            "atr_at_signal": atr,
            "spot_sl":       sl,
            "spot_t1":       t1,
            "spot_t2":       t2,
            "spot_t3":       t3,
            "entry_price":   entry_price,
            "stop_loss_opt": stop_loss_opt,
            "t1_opt":        t1_opt,
            "t2_opt":        t2_opt,
            "t3_opt":        t3_opt,
            "sl_hit":        False,
            "t1_hit":        False,
            "t2_hit":        False,
            "t3_hit":        False,
            "mfe_atr":       0.0,
            "mae_atr":       0.0,
            "status":        "OPEN",
            "lot_size":      lot_size,
            "investment_amt": investment_amt,
            "pnl_sl":        pnl_sl,
            "pnl_t1":        pnl_t1,
            "pnl_t2":        pnl_t2,
            "pnl_t3":        pnl_t3,
        })

        state = {
            "alert_id":      alert_id,
            "index_name":    signal.index_name,
            "direction":     signal.direction,
            "entry_spot":    spot,
            "entry_time":    signal.timestamp,
            "atr":           atr,
            # Spot levels (fallback + post-close reference)
            "sl":            sl,
            "t1":            t1,
            "t2":            t2,
            "t3":            t3,
            # Option premium levels (primary tracking)
            "opt_key":       opt_key,
            "instrument":    getattr(signal, "suggested_instrument", "") or "",
            "entry_price":   entry_price,
            "stop_loss_opt": stop_loss_opt,
            "t1_opt":        t1_opt,
            "t2_opt":        t2_opt,
            "t3_opt":        t3_opt,
            "t1_hit":        False,
            "t2_hit":        False,
            "t3_hit":        False,
            "mfe_atr":       0.0,
            "mae_atr":       0.0,
            "lot_size":      lot_size,
        }

        with self._lock:
            self._open[outcome_id] = state

        enc = signal.index_name.encode("ascii", errors="replace").decode("ascii")
        if opt_key and stop_loss_opt:
            logger.info(
                f"OutcomeTracker: registered {enc} {signal.direction} "
                f"[OPTION] entry={entry_price:.0f} SL={stop_loss_opt:.0f} "
                f"T1={t1_opt:.0f} T2={t2_opt:.0f} T3={t3_opt:.0f} "
                f"[outcome_id={outcome_id}]"
            )
        else:
            logger.info(
                f"OutcomeTracker: registered {enc} {signal.direction} "
                f"[SPOT fallback] SL={sl:.0f} T1={t1:.0f} "
                f"[outcome_id={outcome_id}]"
            )
        return outcome_id

    def tick(self, spot_prices: Dict[str, float],
             option_ltps: Optional[Dict[str, float]] = None) -> List[int]:
        """
        Called on every engine cycle (every 5 seconds).
        Runs both Phase 1 (open) and Phase 2 (post-close) tracking.

        option_ltps — dict keyed by "INDEX:STRIKE:TYPE" e.g. "MIDCPNIFTY:2675:PE"
                       Built from option chain data in main_window each tick.
                       When present, option premium is used for SL/T1/T2/T3 checks.
                       Falls back to spot-based levels when key missing or price 0.

        Returns list of outcome_ids newly closed this tick.
        """
        now    = datetime.now()
        is_eod = self._is_eod(now)
        closed: List[int] = []
        opt_ltps = option_ltps or {}

        with self._lock:
            # ── Phase 1: open trade tracking ──────────────────────
            for oid, state in list(self._open.items()):
                spot = spot_prices.get(state["index_name"])
                if spot is None or spot <= 0:
                    continue

                # ── Layer 2 LTP cache: use cached price if fresh data missing ──
                opt_key   = state.get("opt_key", "")
                fresh_ltp = opt_ltps.get(opt_key) if opt_key else None
                if fresh_ltp and fresh_ltp > 0:
                    # Update cache with fresh value
                    self._ltp_cache[opt_key] = (fresh_ltp, now)
                    opt_price = fresh_ltp
                else:
                    # Try cache fallback
                    cached = self._ltp_cache.get(opt_key)
                    if cached and (now - cached[1]).total_seconds() <= self._LTP_CACHE_MAX_AGE_SEC:
                        opt_price = cached[0]
                    else:
                        opt_price = None

                self._update_excursion(state, spot, opt_price)
                done, reason = self._check_levels(state, spot, opt_price, is_eod)
                if done:
                    self._close(oid, state, spot, reason, now, opt_price)
                    closed.append(oid)

            # ── Phase 2: post-close monitoring ────────────────────
            if is_eod:
                # EOD — finalise all post-close states and flush to DB
                for oid, pc in list(self._post_close.items()):
                    spot = spot_prices.get(pc["index_name"], 0.0)
                    if spot > 0:
                        self._update_post_excursion(pc, spot)
                    self._flush_post_close(oid, pc, spot)
                self._post_close.clear()
            else:
                for oid, pc in list(self._post_close.items()):
                    spot = spot_prices.get(pc["index_name"])
                    if spot is None or spot <= 0:
                        continue
                    self._update_post_excursion(pc, spot)
                    self._check_post_levels(pc, spot, now)

        return closed

    def open_count(self) -> int:
        with self._lock:
            return len(self._open)

    def tracking_count(self) -> int:
        """Total trades being watched: open + post-close."""
        with self._lock:
            return len(self._open) + len(self._post_close)

    # ─── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _is_eod(now: datetime) -> bool:
        now_ist = datetime.now(_IST).time()
        h, m = map(int, config.OUTCOME_EOD_TIME.split(":"))
        return now_ist >= _time(h, m)

    @staticmethod
    def _update_excursion(state: dict, spot: float, opt_price: Optional[float] = None):
        atr = state["atr"] or 1.0
        entry_opt = state.get("entry_price", 0.0) or 0.0
        if opt_price and opt_price > 0 and entry_opt > 0:
            # Option premium tracking: bought the option, so favorable = price went up
            fav = (opt_price - entry_opt) / atr
            adv = (entry_opt - opt_price) / atr
        else:
            # Spot fallback
            entry = state["entry_spot"]
            if state["direction"] == "BULLISH":
                fav = (spot - entry) / atr
                adv = (entry - spot) / atr
            else:
                fav = (entry - spot) / atr
                adv = (spot - entry) / atr
        state["mfe_atr"] = max(state["mfe_atr"], fav)
        state["mae_atr"] = max(state["mae_atr"], adv)

    @staticmethod
    def _check_levels(state: dict, spot: float,
                      opt_price: Optional[float], is_eod: bool):
        """
        Returns (should_close: bool, reason: str).

        Primary: option premium vs stop_loss_opt / t1_opt / t2_opt / t3_opt.
          For any option bought (CE or PE): SL = premium drops to stop_loss_opt,
          T1/T2/T3 = premium rises to those levels.

        Fallback: spot price vs spot_sl / spot_t1 (used when opt_price unavailable).
        """
        sl_opt = state.get("stop_loss_opt", 0.0) or 0.0
        t1_opt = state.get("t1_opt", 0.0) or 0.0
        t2_opt = state.get("t2_opt", 0.0) or 0.0
        t3_opt = state.get("t3_opt", 0.0) or 0.0

        if opt_price and opt_price > 0 and sl_opt > 0:
            # ── Option premium tracking ────────────────────────────
            # Bought option: SL when premium drops to/below stop_loss_opt
            #                T1/T2/T3 when premium rises to/above those levels
            if opt_price <= sl_opt:
                return True, "SL_HIT"
            if t3_opt and opt_price >= t3_opt:
                state["t3_hit"] = True
                state["t2_hit"] = True
                state["t1_hit"] = True
                return True, "T3_HIT"
            if t2_opt and opt_price >= t2_opt and not state["t2_hit"]:
                state["t2_hit"] = True
                state["t1_hit"] = True
                # T2 hit → trail SL to cost; 50% will be booked, remaining is risk-free
                entry_p = state.get("entry_price", 0.0)
                if entry_p > 0:
                    state["stop_loss_opt"] = entry_p
            elif t1_opt and opt_price >= t1_opt and not state["t1_hit"]:
                state["t1_hit"] = True
                # T1 is a milestone only — SL stays at original level
        else:
            # ── Spot fallback ──────────────────────────────────────
            bull = (state["direction"] == "BULLISH")
            if bull:
                if spot <= state["sl"]:
                    return True, "SL_HIT"
                if spot >= state["t3"]:
                    state["t3_hit"] = True
                    state["t2_hit"] = True
                    state["t1_hit"] = True
                    return True, "T3_HIT"
                if spot >= state["t2"] and not state["t2_hit"]:
                    state["t2_hit"] = True
                    state["t1_hit"] = True
                    # T2 hit → trail spot SL to entry (cost)
                    state["sl"] = state["entry_spot"]
                elif spot >= state["t1"] and not state["t1_hit"]:
                    state["t1_hit"] = True   # milestone only
            else:
                if spot >= state["sl"]:
                    return True, "SL_HIT"
                if spot <= state["t3"]:
                    state["t3_hit"] = True
                    state["t2_hit"] = True
                    state["t1_hit"] = True
                    return True, "T3_HIT"
                if spot <= state["t2"] and not state["t2_hit"]:
                    state["t2_hit"] = True
                    state["t1_hit"] = True
                    # T2 hit → trail spot SL to entry (cost)
                    state["sl"] = state["entry_spot"]
                elif spot <= state["t1"] and not state["t1_hit"]:
                    state["t1_hit"] = True   # milestone only

        if is_eod:
            return True, "EOD"
        return False, ""

    def _close(self, outcome_id: int, state: dict, spot: float, reason: str,
               now: datetime, opt_price: Optional[float] = None):
        """
        Persist Phase-1 closure to DB, update ML feature record, fire callback.
        Then immediately move the trade into Phase-2 post-close monitoring.
        EOD-closed trades skip Phase 2 (no further day left to monitor).
        """
        if reason == "SL_HIT":
            outcome_str, label = "LOSS", 0
        elif reason in ("T3_HIT", "T2_HIT"):
            outcome_str, label = "WIN", 1
        elif reason == "EOD":
            label = 1 if state["t1_hit"] else 0
            outcome_str = "WIN" if label else "NEUTRAL"
        else:
            outcome_str, label = "NEUTRAL", 0

        # Compute realized P&L in rupees based on which level was hit.
        # T2→SL case: after T2 hit we trail SL to entry (breakeven). In paper mode
        # we model 50% booked at T2 + 50% closed at entry → partial win.
        _entry_p   = state.get("entry_price", 0.0) or 0.0
        _lot_size  = state.get("lot_size", 1) or 1
        if _entry_p > 0:
            if reason == "SL_HIT" and state["t2_hit"]:
                # T2 was hit earlier → 50% booked at T2 premium, 50% closed at breakeven (entry)
                _t2 = state.get("t2_opt", 0.0) or 0.0
                realized_pnl = round((_t2 - _entry_p) * _lot_size * 0.5, 2) if _t2 > 0 else 0.0
            elif reason == "SL_HIT":
                # Pure SL: use the original stop_loss_opt level
                # Note: after T2 hit, state["stop_loss_opt"] is trailed to entry_price;
                # use opt_price (actual LTP at close) as the most accurate exit.
                _exit_p = (opt_price or state.get("stop_loss_opt", 0.0)) or 0.0
                realized_pnl = round((_exit_p - _entry_p) * _lot_size, 2) if _exit_p > 0 else 0.0
            elif reason == "T3_HIT":
                _exit_p = state.get("t3_opt", 0.0) or (opt_price or 0.0)
                realized_pnl = round((_exit_p - _entry_p) * _lot_size, 2) if _exit_p > 0 else 0.0
            elif state["t2_hit"]:
                # Closed at/after T2 (EOD with T2 hit) — use actual price if available
                _exit_p = (opt_price or state.get("t2_opt", 0.0)) or 0.0
                realized_pnl = round((_exit_p - _entry_p) * _lot_size, 2) if _exit_p > 0 else 0.0
            elif state["t1_hit"]:
                _exit_p = (opt_price or state.get("t1_opt", 0.0)) or 0.0
                realized_pnl = round((_exit_p - _entry_p) * _lot_size, 2) if _exit_p > 0 else 0.0
            else:
                # EOD or neutral — use actual option price if available
                _exit_p = opt_price or 0.0
                realized_pnl = round((_exit_p - _entry_p) * _lot_size, 2) if _exit_p > 0 else 0.0
        else:
            realized_pnl = 0.0

        updates = {
            "status":       "CLOSED",
            "exit_time":    now,
            "exit_reason":  reason,
            "outcome":      outcome_str,
            "sl_hit":       reason == "SL_HIT",
            "t1_hit":       state["t1_hit"],
            "t2_hit":       state["t2_hit"],
            "t3_hit":       reason == "T3_HIT",
            "mfe_atr":      round(state["mfe_atr"], 3),
            "mae_atr":      round(state["mae_atr"], 3),
            "realized_pnl": realized_pnl,
        }
        if reason == "EOD":
            updates["eod_spot"] = spot
        if reason == "SL_HIT":
            updates["sl_hit_time"] = now
            updates["sl_hit_spot"] = spot
        # Record actual option premium at exit
        if opt_price and opt_price > 0:
            updates["exit_price"] = opt_price

        # BUG-3 fix: compute elapsed candles for time-adjusted option outcome label.
        # Options lose theta each 3-min candle; a slow T1 hit is not a true WIN
        # because premium decay likely eroded the option value at the spot target.
        # Sentinel -1.0 means entry_time unknown (rehydrated trade) — DB will skip
        # the time-check so the label degrades gracefully to SL/target hit only.
        candles_to_close = -1.0
        entry_time = state.get("entry_time")
        if entry_time:
            try:
                elapsed_secs = (now - entry_time).total_seconds()
                candles_to_close = round(elapsed_secs / (config.CANDLE_INTERVAL_MINUTES * 60), 2)
            except Exception:
                pass

        try:
            self._db.update_trade_outcome(outcome_id, updates)
            self._db.update_ml_feature_outcome(
                alert_id          = state["alert_id"],
                sl_hit            = reason == "SL_HIT",
                t1_hit            = state["t1_hit"],
                t2_hit            = state["t2_hit"],
                t3_hit            = reason == "T3_HIT",
                max_favorable_atr = state["mfe_atr"],
                max_adverse_atr   = state["mae_atr"],
                candles_to_close  = candles_to_close,
                realized_pnl      = realized_pnl,
            )
        except Exception as e:
            logger.error(f"OutcomeTracker DB write error: {e}")

        del self._open[outcome_id]

        price_info = (f"opt={opt_price:.1f}" if opt_price else f"spot={spot:.1f}")
        logger.info(
            f"OutcomeTracker: CLOSED [{state['index_name']}] "
            f"{reason} → {outcome_str}  {price_info}  "
            f"MFE={state['mfe_atr']:.2f}× ATR  MAE={state['mae_atr']:.2f}× ATR"
        )

        if self._on_close:
            try:
                self._on_close(outcome_id, outcome_str)
            except Exception as e:
                logger.debug(f"OutcomeTracker on_close callback error: {e}")

        # ── Phase 2: start post-close monitoring (except EOD) ─────
        # For SL-closed trades especially: track whether price recovered.
        if reason != "EOD":
            self._post_close[outcome_id] = {
                "outcome_id":   outcome_id,
                "alert_id":     state["alert_id"],
                "index_name":   state["index_name"],
                "direction":    state["direction"],
                "entry_spot":   state["entry_spot"],
                "close_spot":   spot,
                "atr":          state["atr"],
                "sl":           state["sl"],
                "t1":           state["t1"],
                "t2":           state["t2"],
                "t3":           state["t3"],
                "close_reason": reason,
                # Post-close hit tracking
                "pc_t1_hit":    False,
                "pc_t1_time":   None,
                "pc_t2_hit":    False,
                "pc_t2_time":   None,
                "pc_t3_hit":    False,
                "pc_t3_time":   None,
                "pc_mfe_atr":   0.0,
                "pc_mae_atr":   0.0,
            }
            logger.debug(
                f"OutcomeTracker: Phase-2 monitoring started [{state['index_name']}] "
                f"after {reason}"
            )

    # ─── Phase-2 post-close helpers ──────────────────────────────

    @staticmethod
    def _update_post_excursion(pc: dict, spot: float):
        """Track MFE/MAE from the close spot (not the entry spot)."""
        ref = pc["close_spot"]
        atr = pc["atr"] or 1.0
        if pc["direction"] == "BULLISH":
            fav = (spot - ref) / atr
            adv = (ref - spot) / atr
        else:
            fav = (ref - spot) / atr
            adv = (spot - ref) / atr
        pc["pc_mfe_atr"] = max(pc["pc_mfe_atr"], fav)
        pc["pc_mae_atr"] = max(pc["pc_mae_atr"], adv)

    @staticmethod
    def _check_post_levels(pc: dict, spot: float, now: datetime):
        """Record if price hits T1/T2/T3 AFTER the trade was closed."""
        bull = (pc["direction"] == "BULLISH")
        if bull:
            if spot >= pc["t3"] and not pc["pc_t3_hit"]:
                pc["pc_t3_hit"] = True
                pc["pc_t3_time"] = now
                pc["pc_t2_hit"] = True
                pc["pc_t1_hit"] = True
            elif spot >= pc["t2"] and not pc["pc_t2_hit"]:
                pc["pc_t2_hit"] = True
                pc["pc_t2_time"] = now
                pc["pc_t1_hit"] = True
            elif spot >= pc["t1"] and not pc["pc_t1_hit"]:
                pc["pc_t1_hit"] = True
                pc["pc_t1_time"] = now
        else:
            if spot <= pc["t3"] and not pc["pc_t3_hit"]:
                pc["pc_t3_hit"] = True
                pc["pc_t3_time"] = now
                pc["pc_t2_hit"] = True
                pc["pc_t1_hit"] = True
            elif spot <= pc["t2"] and not pc["pc_t2_hit"]:
                pc["pc_t2_hit"] = True
                pc["pc_t2_time"] = now
                pc["pc_t1_hit"] = True
            elif spot <= pc["t1"] and not pc["pc_t1_hit"]:
                pc["pc_t1_hit"] = True
                pc["pc_t1_time"] = now

    def _flush_post_close(self, outcome_id: int, pc: dict, eod_spot: float):
        """Write accumulated post-close data to DB at EOD."""
        sl_was_hit      = pc["close_reason"] == "SL_HIT"
        reversal        = sl_was_hit and pc["pc_t1_hit"]
        full_recovery   = sl_was_hit and pc["pc_t3_hit"]
        try:
            self._db.update_post_close_outcome(
                outcome_id             = outcome_id,
                alert_id               = pc["alert_id"],
                post_close_t1_hit      = pc["pc_t1_hit"],
                post_close_t2_hit      = pc["pc_t2_hit"],
                post_close_t3_hit      = pc["pc_t3_hit"],
                post_close_max_fav_atr = pc["pc_mfe_atr"],
                post_close_max_adv_atr = pc["pc_mae_atr"],
                post_close_eod_spot    = eod_spot,
                post_sl_reversal       = reversal,
                post_sl_full_recovery  = full_recovery,
                t1_hit_time            = pc["pc_t1_time"],
                t2_hit_time            = pc["pc_t2_time"],
                t3_hit_time            = pc["pc_t3_time"],
            )
            if sl_was_hit and reversal:
                idx = pc["index_name"].encode("ascii", errors="replace").decode("ascii")
                logger.info(
                    f"PostClose [{idx}]: SL was too tight — price recovered to "
                    f"{'T3' if full_recovery else 'T1/T2'} after close  "
                    f"post_MFE={pc['pc_mfe_atr']:.2f}×ATR"
                )
        except Exception as e:
            logger.error(f"OutcomeTracker flush_post_close error: {e}")

    def _rehydrate(self):
        """Load OPEN outcomes from a previous session on startup."""
        try:
            rows = self._db.get_open_outcomes()
            for row in rows:
                if not all([row.direction, row.entry_spot, row.atr_at_signal,
                             row.spot_sl, row.spot_t1, row.spot_t2, row.spot_t3]):
                    continue
                # Rebuild opt_key from instrument name stored in DB
                instr      = row.instrument or ""
                opt_key    = None
                entry_price    = row.entry_price or 0.0
                stop_loss_opt  = row.stop_loss_opt or 0.0
                t1_opt         = row.t1_opt or 0.0
                t2_opt         = row.t2_opt or 0.0
                t3_opt         = row.t3_opt or 0.0
                # Try to extract strike + type from instrument string e.g. MIDCPNIFTY30-03-212675PE
                try:
                    if instr and (instr.endswith("CE") or instr.endswith("PE")):
                        opt_type = instr[-2:]
                        # Find the numeric strike between index prefix and CE/PE suffix
                        import re as _re
                        m = _re.search(r"(\d{3,6})(CE|PE)$", instr)
                        if m:
                            strike_val = int(m.group(1))
                            opt_key = f"{row.index_name}:{strike_val}:{opt_type}"
                except Exception:
                    pass

                self._open[row.id] = {
                    "alert_id":      row.alert_id,
                    "index_name":    row.index_name,
                    "direction":     row.direction,
                    "entry_spot":    row.entry_spot,
                    "entry_time":    row.entry_time,
                    "atr":           row.atr_at_signal,
                    "sl":            row.spot_sl,
                    "t1":            row.spot_t1,
                    "t2":            row.spot_t2,
                    "t3":            row.spot_t3,
                    "opt_key":       opt_key,
                    "entry_price":   entry_price,
                    "stop_loss_opt": stop_loss_opt,
                    "t1_opt":        t1_opt,
                    "t2_opt":        t2_opt,
                    "t3_opt":        t3_opt,
                    "t1_hit":        bool(row.t1_hit),
                    "t2_hit":        bool(row.t2_hit),
                    "t3_hit":        bool(row.t3_hit),
                    "mfe_atr":       row.mfe_atr or 0.0,
                    "mae_atr":       row.mae_atr or 0.0,
                }
            if self._open:
                logger.info(f"OutcomeTracker: re-hydrated {len(self._open)} open trade(s) from previous session")
        except Exception as e:
            logger.warning(f"OutcomeTracker rehydrate error: {e}")
