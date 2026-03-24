"""
trading/order_manager.py
─────────────────────────────────────────────────────────────────
Layer 1 auto trading: places Fyers bracket orders (BO) when a
confirmed trade signal fires.

Three operating modes (set via dashboard toggle):
  OFF   — no orders placed, no simulation
  PAPER — simulates orders without real broker calls;
           P&L is computed from live OutcomeTracker data
  LIVE  — real Fyers bracket orders placed at exchange level

A bracket order (BO) is a single exchange-level order that bundles:
  • Entry (market or limit)
  • Stop Loss leg  — broker cancels if entry not filled
  • Target leg     — broker cancels if SL is hit

Paper trading signal flow:
  CONFIRMED_SIGNAL → place_order() → fake order_id generated →
  OutcomeTracker tracks SL/T1/T2/T3 hits on live LTP every 5 s →
  refresh_order_status() reads OutcomeTracker to compute P&L

Live trading signal flow:
  CONFIRMED_SIGNAL → place_order() → fyers.place_order() →
  broker BO live at exchange → refresh_order_status() polls Fyers

Usage:
    om = OrderManager()
    om.set_mode("PAPER")   # or "LIVE" or "OFF"
    oid = om.place_order(signal, expiry="30-03-2025")
    summary = om.get_today_summary()
"""

import logging
import threading
from calendar import monthrange
from datetime import date, datetime
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# Fyers month codes for weekly option symbols
# Monthly expiry (last Thursday) uses 3-letter abbreviation (MAR, APR…)
# Weekly uses single char: 1-9 for Jan-Sep, O=Oct, N=Nov, D=Dec
_MONTH_ABBR  = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MONTH_CODE  = ["1", "2", "3", "4", "5", "6",
                "7", "8", "9", "O", "N", "D"]

# Exchange prefix per index
_EXCHANGE = {
    "NIFTY":      "NSE",
    "BANKNIFTY":  "NSE",
    "MIDCPNIFTY": "NSE",
    "SENSEX":     "BSE",
}

# Expiry weekday: NSE → Thursday (3), BSE → Friday (4)
_EXPIRY_WEEKDAY = {
    "NSE": 3,   # Thursday
    "BSE": 4,   # Friday
}


def _last_expiry_day(year: int, month: int, weekday: int) -> int:
    """Return the day number of the last <weekday> in the given month."""
    _, last = monthrange(year, month)
    d = last
    while date(year, month, d).weekday() != weekday:
        d -= 1
    return d


def build_fyers_symbol(index_name: str, strike: float,
                        option_type: str, expiry_str: str) -> Optional[str]:
    """
    Build the Fyers option trading symbol from signal components.

    expiry_str formats accepted:
      "30-03-2025"  (DD-MM-YYYY — from Fyers chain.expiry)
      "30MAR2025"   (DDMMMYYYY  — from expiry calendar override)

    Returns e.g. "NSE:NIFTY25MAR23300CE"  (monthly)
              or "NSE:NIFTY2533023300CE"  (weekly)
    Returns None if parsing fails.
    """
    try:
        # ── Parse expiry date ──────────────────────────────────────
        if len(expiry_str) >= 10 and expiry_str[2] == "-":
            # DD-MM-YYYY
            day   = int(expiry_str[0:2])
            month = int(expiry_str[3:5])
            year  = int(expiry_str[6:10])
        elif len(expiry_str) >= 9 and expiry_str[2:5].isalpha():
            # DDMMMYYYY
            month_map = {m: i + 1 for i, m in enumerate(_MONTH_ABBR)}
            day   = int(expiry_str[0:2])
            month = month_map.get(expiry_str[2:5].upper(), 0)
            year  = int(expiry_str[5:9])
        else:
            logger.warning(f"build_fyers_symbol: unrecognised expiry format: {expiry_str!r}")
            return None

        if not (1 <= month <= 12 and 1 <= day <= 31 and year > 2000):
            return None

        exchange   = _EXCHANGE.get(index_name, "NSE")
        exp_wkday  = _EXPIRY_WEEKDAY.get(exchange, 3)
        last_exp_d = _last_expiry_day(year, month, exp_wkday)
        yy         = str(year)[-2:]           # "2025" → "25"
        strike_int = int(strike)

        # ── Monthly vs weekly ──────────────────────────────────────
        if day == last_exp_d:
            # Monthly expiry — YYMON format
            expiry_code = yy + _MONTH_ABBR[month - 1]   # "25MAR"
        else:
            # Weekly expiry — YYMDD (single-char month code + zero-padded day)
            expiry_code = yy + _MONTH_CODE[month - 1] + f"{day:02d}"  # "25330"

        return f"{exchange}:{index_name}{expiry_code}{strike_int}{option_type}"

    except Exception as e:
        logger.warning(f"build_fyers_symbol error ({expiry_str!r}): {e}")
        return None


class OrderManager:
    """
    Places and tracks orders for auto/paper trading.

    Thread-safe; all state mutations are protected by self._lock.

    Mode states:
      "OFF"   — disabled, no orders
      "PAPER" — simulated orders, real P&L from OutcomeTracker
      "LIVE"  — real Fyers bracket orders
    """

    def __init__(self):
        self._lock         = threading.Lock()
        # Mode: "OFF" | "PAPER" | "LIVE"
        self._mode         = "OFF"
        # Active orders this session  {order_id: order_dict}
        self._open_orders: Dict[str, dict]   = {}
        # All orders today (open + closed) for P&L and count
        self._today_orders: List[dict]       = []
        self._today_date   = date.today()
        # Fyers API instance (lazy-loaded from adapter, only used in LIVE mode)
        self._fyers        = None
        # Per-index dedup: do not place a second order for the same alert_id
        self._placed_alert_ids: set = set()
        # OutcomeTracker reference — injected from main_window for paper P&L
        self._outcome_tracker = None
        # Paper order counter for generating unique fake IDs
        self._paper_counter = 0

    # ─── Public API ──────────────────────────────────────────────

    def set_mode(self, mode: str):
        """Set operating mode: 'OFF', 'PAPER', or 'LIVE'."""
        mode = mode.upper()
        if mode not in ("OFF", "PAPER", "LIVE"):
            logger.warning(f"OrderManager.set_mode: invalid mode {mode!r}")
            return
        with self._lock:
            self._mode = mode
        logger.info(f"Auto trading mode: {mode}")

    def get_mode(self) -> str:
        with self._lock:
            return self._mode

    def is_enabled(self) -> bool:
        """True when mode is PAPER or LIVE."""
        with self._lock:
            return self._mode in ("PAPER", "LIVE")

    # Legacy helpers kept for compatibility with dashboard/main_window
    def set_enabled(self, enabled: bool):
        """Enable = LIVE mode, disable = OFF. Use set_mode() for PAPER."""
        self.set_mode("LIVE" if enabled else "OFF")

    def set_outcome_tracker(self, ot):
        """Inject OutcomeTracker so paper mode can read live SL/T1 hits."""
        self._outcome_tracker = ot

    def place_order(self, signal, expiry: str = "",
                    live_ltp: float = 0.0) -> Optional[str]:
        """
        Place or simulate a bracket order for the given TradeSignal.

        expiry    — chain expiry string "DD-MM-YYYY" (from dm.get_option_chain)
        live_ltp  — current option LTP fetched at order-placement time.
                    If > 0, this overrides signal.entry_reference so the order
                    uses the candle-close price rather than the stale signal price.
                    Falls back to signal.entry_reference when 0.

        PAPER mode: generates a fake order_id, tracks internally, computes
                    P&L from live OutcomeTracker SL/T1 hits.
        LIVE mode:  calls fyers.place_order(), tracks the real order_id.

        Quality gates (all must pass):
          • Mode is PAPER or LIVE
          • Daily order cap not reached
          • Signal confidence >= AUTO_TRADE_MIN_CONFIDENCE
          • Signal engines_count >= AUTO_TRADE_MIN_ENGINES
          • Not already placed for this alert_id

        Returns order_id string, or None on failure / gate rejection.
        """
        self._maybe_reset_daily()

        with self._lock:
            mode = self._mode
            if mode == "OFF":
                return None

            if len(self._today_orders) >= config.AUTO_TRADE_MAX_DAILY_ORDERS:
                logger.info(
                    f"AutoTrade [{mode}]: daily cap "
                    f"{config.AUTO_TRADE_MAX_DAILY_ORDERS} reached — skipping"
                )
                return None

            conf    = getattr(signal, "confidence_score", 0.0) or 0.0
            engines = len(getattr(signal, "engines_triggered", []) or [])
            if conf < config.AUTO_TRADE_MIN_CONFIDENCE:
                logger.info(f"AutoTrade [{mode}]: SKIPPED conf={conf:.1f}% < "
                            f"min={config.AUTO_TRADE_MIN_CONFIDENCE}% "
                            f"[{getattr(signal,'index_name','')} {getattr(signal,'direction','')}]")
                return None
            if engines < config.AUTO_TRADE_MIN_ENGINES:
                logger.info(f"AutoTrade [{mode}]: SKIPPED engines={engines} < "
                            f"min={config.AUTO_TRADE_MIN_ENGINES} "
                            f"[{getattr(signal,'index_name','')} {getattr(signal,'direction','')}]")
                return None

            aid = getattr(signal, "alert_id", 0) or 0
            if aid and aid in self._placed_alert_ids:
                logger.info(f"AutoTrade [{mode}]: SKIPPED alert_id={aid} already placed "
                            f"[{getattr(signal,'index_name','')} {getattr(signal,'direction','')}]")
                return None

        # ── Build shared order payload ────────────────────────────
        order_data = self._build_order(signal, expiry, live_ltp=live_ltp)
        if order_data is None:
            logger.warning(f"AutoTrade [{mode}]: could not build order payload — skip")
            return None

        # ── PAPER MODE: simulate without Fyers call ───────────────
        if mode == "PAPER":
            with self._lock:
                self._paper_counter += 1
                order_id = f"PAPER-{self._paper_counter:04d}"

            # Use live_ltp (candle-close price) as the simulated fill price.
            # Fall back to signal.entry_reference only if live_ltp unavailable.
            entry   = live_ltp if live_ltp > 0 else float(getattr(signal, "entry_reference", 0) or 0)
            sl_abs  = float(getattr(signal, "stop_loss_reference", 0) or 0)
            t1_abs  = float(getattr(signal, "target_reference", 0) or
                            getattr(signal, "target1", 0) or 0)

            # Recompute sl_abs / t1_abs relative to the live entry so the
            # ATR offsets land at the correct option price levels.
            if live_ltp > 0 and float(getattr(signal, "entry_reference", 0) or 0) > 0:
                old_entry = float(getattr(signal, "entry_reference", 0))
                sl_offset = old_entry - sl_abs          # points below old entry
                tp_offset = t1_abs   - old_entry        # points above old entry
                sl_abs = max(1.0, entry - sl_offset)
                t1_abs = entry + tp_offset
            order_record = {
                "order_id":   order_id,
                "alert_id":   aid,
                "symbol":     order_data["symbol"],
                "index_name": getattr(signal, "index_name", ""),
                "direction":  getattr(signal, "direction", ""),
                "qty":        order_data["qty"],
                "entry":      entry,
                "sl":         sl_abs,
                "tp":         t1_abs,
                # Also store raw option levels for P&L calculation
                "sl_opt":     sl_abs,
                "tp_opt":     t1_abs,
                "status":     "PAPER-OPEN",
                "placed_at":  datetime.now(),
                "pnl":        0.0,
                "mode":       "PAPER",
            }
            with self._lock:
                self._open_orders[order_id] = order_record
                self._today_orders.append(order_record)
                if aid:
                    self._placed_alert_ids.add(aid)

            logger.info(
                f"AutoTrade [PAPER]: SIMULATED {order_data['symbol']} "
                f"qty={order_data['qty']} entry={entry:.1f} "
                f"SL={sl_abs:.1f} T1={t1_abs:.1f} → {order_id}"
            )
            return order_id

        # ── LIVE MODE: real Fyers bracket order ───────────────────
        fyers = self._get_fyers()
        if fyers is None:
            logger.warning("AutoTrade [LIVE]: Fyers not connected — cannot place order")
            return None

        try:
            resp = fyers.place_order(data=order_data)
            if resp.get("s") != "ok":
                msg = resp.get("message", resp)
                logger.error(f"AutoTrade [LIVE]: Fyers order rejected: {msg}")
                return None

            order_id = str(resp.get("id", ""))
            logger.info(
                f"AutoTrade [LIVE]: ORDER PLACED {order_data['symbol']} "
                f"qty={order_data['qty']} "
                f"entry={order_data.get('limitPrice', 'MKT')} "
                f"SL_offset={order_data.get('stopLoss', '?')} "
                f"TP_offset={order_data.get('takeProfit', '?')} "
                f"→ order_id={order_id}"
            )
            order_record = {
                "order_id":   order_id,
                "alert_id":   aid,
                "symbol":     order_data["symbol"],
                "index_name": getattr(signal, "index_name", ""),
                "direction":  getattr(signal, "direction", ""),
                "qty":        order_data["qty"],
                "entry":      order_data.get("limitPrice", 0.0),
                "sl":         order_data.get("stopLoss", 0.0),
                "tp":         order_data.get("takeProfit", 0.0),
                "status":     "OPEN",
                "placed_at":  datetime.now(),
                "pnl":        0.0,
                "mode":       "LIVE",
            }
            with self._lock:
                self._open_orders[order_id] = order_record
                self._today_orders.append(order_record)
                if aid:
                    self._placed_alert_ids.add(aid)
            return order_id

        except Exception as e:
            logger.error(f"AutoTrade [LIVE]: place_order exception: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific open bracket order."""
        fyers = self._get_fyers()
        if fyers is None:
            return False
        try:
            resp = fyers.cancel_order(data={"id": order_id})
            ok = resp.get("s") == "ok"
            if ok:
                with self._lock:
                    rec = self._open_orders.pop(order_id, None)
                    if rec:
                        rec["status"] = "CANCELLED"
                logger.info(f"AutoTrade: cancelled order {order_id}")
            return ok
        except Exception as e:
            logger.error(f"AutoTrade: cancel_order {order_id} error: {e}")
            return False

    def refresh_order_status(self):
        """
        Update status of all open orders.
        Called by a background timer every 15 s.

        PAPER mode: reads OutcomeTracker to check if SL/T1 was hit,
                    computes P&L from actual option LTP movement.
        LIVE mode:  polls Fyers orderbook for fill / cancel status.
        """
        with self._lock:
            mode = self._mode
            if not self._open_orders:
                return

        if mode == "PAPER":
            self._refresh_paper_orders()
        elif mode == "LIVE":
            self._refresh_live_orders()

    def _refresh_paper_orders(self):
        """Update paper orders by checking OutcomeTracker for closed outcomes."""
        ot = self._outcome_tracker
        if ot is None:
            return
        try:
            # Snapshot OutcomeTracker state (thread-safe)
            with ot._lock:
                open_ot   = dict(ot._open)
                closed_db = {}   # we need DB for already-closed outcomes

            with self._lock:
                for oid, rec in list(self._open_orders.items()):
                    if rec.get("mode") != "PAPER":
                        continue
                    if rec["status"] not in ("PAPER-OPEN",):
                        continue

                    aid = rec.get("alert_id", 0)
                    if not aid:
                        continue

                    # Find matching OutcomeTracker state by alert_id
                    matched_state = None
                    for outcome_id, state in open_ot.items():
                        if state.get("alert_id") == aid:
                            matched_state = state
                            break

                    if matched_state:
                        # Still open — update live P&L estimate from MFE/MAE
                        entry_opt = matched_state.get("entry_price", 0.0) or 0.0
                        atr       = matched_state.get("atr", 1.0) or 1.0
                        mfe       = matched_state.get("mfe_atr", 0.0)
                        mae       = matched_state.get("mae_atr", 0.0)
                        if entry_opt > 0:
                            # Best unrealised P&L based on MFE
                            best_move = mfe * atr
                            rec["pnl"] = round(best_move * rec["qty"], 2)
                            rec["status"] = "PAPER-OPEN"
                    else:
                        # Not in open tracker — check DB for closed outcome
                        try:
                            from database.manager import get_db
                            _db = get_db()
                            outcome = _db.get_trade_outcome_by_alert(aid)
                            if outcome and outcome.status == "CLOSED":
                                entry  = rec.get("entry", 0.0) or 0.0
                                qty    = rec.get("qty", 1)
                                sl_opt = outcome.stop_loss_opt or rec.get("sl_opt", 0.0) or 0.0
                                t2_opt = outcome.t2_opt or 0.0
                                t3_opt = outcome.t3_opt or 0.0
                                tp_opt = outcome.t1_opt or rec.get("tp_opt", 0.0) or 0.0
                                exit_p = outcome.exit_price or entry

                                # ── Booking strategy ──────────────────────────────
                                # T1 hit → milestone only, SL unchanged, full pos open
                                # T2 hit → 50% booked at T2, SL trails to cost
                                # T3 hit → remaining 50% booked at T3
                                # SL before T2 → full loss at original SL
                                # SL after T2 (at cost) → 50% T2 profit, 0 on rest
                                if outcome.t3_hit:
                                    # 50% at T2 + 50% at T3
                                    pnl = ((t2_opt - entry) * qty * 0.5
                                           + (t3_opt - entry) * qty * 0.5)
                                    rec["status"] = "PAPER-T3"
                                elif outcome.t2_hit:
                                    # 50% at T2; remaining 50% closed at cost (SL@cost)
                                    # or at exit_price if EOD — never below cost
                                    remaining_pnl = max(0.0, (exit_p - entry)) * qty * 0.5
                                    pnl = (t2_opt - entry) * qty * 0.5 + remaining_pnl
                                    rec["status"] = "PAPER-T2"
                                elif outcome.sl_hit:
                                    # SL hit (before T2 was reached) — full loss
                                    pnl = (sl_opt - entry) * qty if entry > 0 else 0.0
                                    rec["status"] = "PAPER-SL"
                                else:
                                    # EOD close or T1-only — use actual exit price
                                    pnl = (exit_p - entry) * qty if entry > 0 else 0.0
                                    rec["status"] = "PAPER-T1" if outcome.t1_hit else "PAPER-EOD"
                                rec["pnl"] = round(pnl, 2)
                                # Move out of open (keep in today_orders for summary)
                                self._open_orders.pop(oid, None)
                                logger.info(
                                    f"AutoTrade [PAPER]: {oid} closed "
                                    f"{rec['status']} P&L={rec['pnl']:+.0f}"
                                )
                        except Exception as e:
                            logger.debug(f"AutoTrade paper DB check error: {e}")
        except Exception as e:
            logger.debug(f"AutoTrade _refresh_paper_orders error: {e}")

    def _refresh_live_orders(self):
        """Poll Fyers orderbook and update live order status."""
        fyers = self._get_fyers()
        if fyers is None:
            return
        try:
            resp = fyers.orderbook()
            if resp.get("s") != "ok":
                return
            orders     = resp.get("orderBook", [])
            status_map = {str(o.get("id", "")): o for o in orders}
            with self._lock:
                for oid, rec in list(self._open_orders.items()):
                    if rec.get("mode") != "LIVE":
                        continue
                    broker_rec    = status_map.get(oid)
                    if broker_rec is None:
                        continue
                    broker_status = str(broker_rec.get("status", "")).upper()
                    # Fyers: 2=traded, 1=cancelled, 5=rejected
                    if broker_status in ("2", "TRADED", "FILLED"):
                        fill = float(broker_rec.get("tradedPrice", rec["entry"]) or 0)
                        rec["entry"]  = fill
                        rec["status"] = "FILLED"
                    elif broker_status in ("1", "5", "CANCELLED", "REJECTED"):
                        rec["status"] = broker_status
                        self._open_orders.pop(oid, None)
        except Exception as e:
            logger.debug(f"AutoTrade _refresh_live_orders error: {e}")

    def get_open_orders(self) -> List[dict]:
        """Return a snapshot of currently open/filled orders."""
        with self._lock:
            return list(self._open_orders.values())

    def get_today_summary(self) -> dict:
        """Return today's order count, mode, and estimated P&L."""
        self._maybe_reset_daily()
        with self._lock:
            placed = len(self._today_orders)
            cap    = config.AUTO_TRADE_MAX_DAILY_ORDERS
            pnl    = sum(o.get("pnl", 0.0) for o in self._today_orders)
            wins   = sum(1 for o in self._today_orders
                         if o.get("status", "").endswith(("T1", "T2", "T3", "FILLED")))
            losses = sum(1 for o in self._today_orders
                         if o.get("status", "").endswith("SL"))
            return {
                "mode":      self._mode,
                "placed":    placed,
                "remaining": max(0, cap - placed),
                "cap":       cap,
                "pnl":       pnl,
                "wins":      wins,
                "losses":    losses,
                "enabled":   self._mode != "OFF",
            }

    # ─── Internal helpers ────────────────────────────────────────

    def _maybe_reset_daily(self):
        today = date.today()
        with self._lock:
            if today != self._today_date:
                self._today_date     = today
                self._today_orders   = []
                self._open_orders    = {}
                self._placed_alert_ids = set()
                logger.info("AutoTrade: new trading day — daily counters reset")

    def _get_fyers(self):
        """Lazily fetch the live Fyers API handle from the adapter."""
        if self._fyers is not None:
            return self._fyers
        try:
            from data.adapters.fyers_adapter import FyersAdapter
            # FyersAdapter is a singleton via the data manager; access its _fyers handle
            # by re-creating one and connecting with the cached token.
            adapter = FyersAdapter()
            adapter.connect()
            if adapter._fyers:
                self._fyers = adapter._fyers
                return self._fyers
        except Exception as e:
            logger.debug(f"AutoTrade: _get_fyers error: {e}")
        return None

    def _build_order(self, signal, expiry: str = "",
                     live_ltp: float = 0.0) -> Optional[dict]:
        """
        Build the Fyers bracket order payload dict.

        live_ltp — current option LTP at order-placement time. When > 0 it
                   overrides signal.entry_reference for limit-price and for
                   computing BO SL/TP offsets so they are anchored to the
                   actual candle-close price, not the stale signal price.

        Fyers BO fields:
          symbol      — exchange:instrument e.g. "NSE:NIFTY25MAR23300CE"
          qty         — total quantity (lot_size × num_lots)
          type        — 1=limit, 2=market
          side        — 1=buy (we always buy options)
          productType — "BO"
          limitPrice  — entry price (0 for market)
          stopPrice   — 0 (not used for BO)
          stopLoss    — SL offset from fill price (absolute points)
          takeProfit  — Target offset from fill price (absolute points)
          validity    — "DAY"
        """
        # ── Extract signal fields ──────────────────────────────────
        index_name  = getattr(signal, "index_name", "")
        strike      = float(getattr(signal, "strike", 0) or 0)
        option_type = getattr(signal, "option_type", "CE") or "CE"
        sig_entry   = float(getattr(signal, "entry_reference", 0) or 0)
        sl_price    = float(getattr(signal, "stop_loss_reference", 0) or 0)
        t1_price    = float(getattr(signal, "target_reference", 0) or
                            getattr(signal, "target1", 0) or 0)

        # Use live_ltp as entry when available — it reflects the actual
        # candle-close option price rather than the stale signal price.
        entry_price = live_ltp if live_ltp > 0 else sig_entry

        # Keep ATR-based offsets but re-anchor them to the live entry.
        # This ensures SL/TP levels land correctly even if the option
        # price moved between signal generation and candle-close.
        if live_ltp > 0 and sig_entry > 0:
            sl_offset_pts = sig_entry - sl_price    # ATR offset below old entry
            tp_offset_pts = t1_price  - sig_entry   # ATR offset above old entry
            sl_price = max(1.0, entry_price - sl_offset_pts)
            t1_price = entry_price + tp_offset_pts

        if not expiry:
            logger.warning(f"AutoTrade: no expiry for {index_name} — cannot build symbol")
            return None

        # ── Build Fyers tradeable symbol ───────────────────────────
        fyers_symbol = build_fyers_symbol(index_name, strike, option_type, expiry)
        if not fyers_symbol:
            logger.warning(f"AutoTrade: build_fyers_symbol failed for {index_name} "
                           f"strike={strike} {option_type} expiry={expiry}")
            return None

        # ── Quantity ───────────────────────────────────────────────
        lot_size = config.SYMBOL_MAP.get(index_name, {}).get("lot_size", 1)
        pos_info = getattr(signal, "raw_features", {}).get("_position", {})
        rec_lots = int(pos_info.get("recommended_lots", 1) or 1)
        num_lots = max(1, rec_lots * config.AUTO_TRADE_LOT_MULTIPLIER)
        qty      = int(lot_size * num_lots)

        # ── Price levels ───────────────────────────────────────────
        # BO uses offsets from the market fill price, not absolute levels.
        # For market orders, entry_price ≈ current LTP. We compute:
        #   SL offset  = |entry - sl_price|
        #   TP offset  = |t1_price - entry|
        if entry_price > 0 and sl_price > 0 and t1_price > 0:
            sl_offset = abs(entry_price - sl_price)  + config.AUTO_TRADE_SL_BUFFER
            tp_offset = abs(t1_price   - entry_price) + config.AUTO_TRADE_TP_BUFFER
            sl_offset = round(sl_offset, 1)
            tp_offset = round(tp_offset, 1)
        else:
            logger.warning(f"AutoTrade: price levels missing for {fyers_symbol} — skip")
            return None

        order_type = config.AUTO_TRADE_ORDER_TYPE   # 1=limit, 2=market
        limit_price = round(entry_price, 1) if order_type == 1 else 0

        return {
            "symbol":       fyers_symbol,
            "qty":          qty,
            "type":         order_type,
            "side":         1,           # always BUY — we buy CE or PE
            "productType":  "BO",
            "limitPrice":   limit_price,
            "stopPrice":    0,
            "stopLoss":     sl_offset,
            "takeProfit":   tp_offset,
            "validity":     "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
