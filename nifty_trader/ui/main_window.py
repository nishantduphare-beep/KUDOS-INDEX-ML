"""
ui/main_window.py
Main application window — 5 tabs including Credentials.
Wires DataManager → SignalAggregator → AlertManager → ML pipeline.
"""

import sys
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget,
    QWidget, QVBoxLayout, QLabel, QStatusBar
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot
from PySide6.QtGui import QColor

import config
from ui.dashboard_tab    import DashboardTab
from ui.scanner_tab      import ScannerTab
from ui.options_flow_tab import OptionsFlowTab
from ui.alerts_tab       import AlertsTab
from ui.hq_trades_tab    import HQTradesTab
from ui.credentials_tab  import CredentialsTab
from ui.ml_report_widget import MLReportWidget
from ui.ledger_tab       import LedgerTab
from ui.setup_tab              import SetupTab
from ui.s11_tab                import S11Tab
from ui.ml_testing_tab         import MLTestingTab
from ui.deployment_control_panel import DeploymentControlPanel

logger = logging.getLogger(__name__)

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: "Consolas", "JetBrains Mono", "Courier New", monospace;
    font-size: 13px;
}
QTabWidget::pane { border: 1px solid #30363d; background: #0d1117; }
QTabBar::tab {
    background: #161b22; color: #8b949e;
    padding: 8px 18px; border: 1px solid #30363d; border-bottom: none;
    font-size: 12px; font-weight: bold; letter-spacing: 1px; min-width: 110px;
}
QTabBar::tab:selected { background: #0d1117; color: #58a6ff; border-top: 2px solid #58a6ff; }
QTabBar::tab:hover    { background: #21262d; color: #c9d1d9; }
QTableWidget {
    background: #0d1117; gridline-color: #21262d; border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #21262d; }
QHeaderView::section {
    background: #161b22; color: #8b949e; padding: 6px 8px;
    border: none; border-right: 1px solid #30363d;
    font-size: 11px; font-weight: bold; letter-spacing: 0.5px;
}
QScrollBar:vertical { background:#161b22; width:8px; border-radius:4px; }
QScrollBar::handle:vertical { background:#30363d; border-radius:4px; min-height:30px; }
QLabel { color: #c9d1d9; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #30363d; }
QPushButton {
    background:#21262d; color:#c9d1d9; border:1px solid #30363d;
    padding:6px 16px; border-radius:4px; font-weight:bold;
}
QPushButton:hover  { background:#30363d; border-color:#58a6ff; }
QPushButton:pressed { background:#1f6feb; }
QComboBox {
    background:#161b22; color:#c9d1d9; border:1px solid #30363d;
    padding:4px 8px; border-radius:3px;
}
QSplitter::handle { background:#30363d; }
QGroupBox {
    color:#8b949e; border:1px solid #30363d; border-radius:5px;
    margin-top:10px; padding-top:6px; font-size:10px; letter-spacing:1px;
}
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px; }
QLineEdit {
    background:#0d1117; color:#e6edf3; border:1px solid #30363d;
    border-radius:4px; padding:6px 10px; font-size:12px;
}
QLineEdit:focus { border-color:#58a6ff; }
QTextEdit {
    background:#0d1117; color:#e6edf3; border:1px solid #30363d; border-radius:4px;
}
QProgressBar { background:#21262d; border-radius:3px; border:none; }
QProgressBar::chunk { background:#3fb950; border-radius:3px; }
QCheckBox { color:#c9d1d9; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #30363d; border-radius:2px; background:#161b22; }
QCheckBox::indicator:checked { background:#1f6feb; border-color:#1f6feb; }
"""


class DataBridge(QObject):
    data_updated          = Signal()
    alert_received        = Signal(object)
    model_updated         = Signal(object)
    engine_result         = Signal(str, int, float, str, str, str)  # idx, count, conf, b5, b15, align
    outcome_updated       = Signal(int, str)                         # outcome_id, outcome_str
    s11_position_changed  = Signal()                                 # fired on S11 open/close


class MainWindow(QMainWindow):

    def __init__(self, data_manager, signal_aggregator, alert_manager):
        super().__init__()
        self._dm  = data_manager
        self._sa  = signal_aggregator
        self._am  = alert_manager
        self._bridge = DataBridge()

        # Candle-close confirmation buffer  {index_name: TradeSignal}
        # Holds the most recent TradeSignal per index within the current candle.
        # When a new candle opens, each buffered signal fires once as CONFIRMED.
        import threading as _threading
        self._pending_confirm: dict = {}
        self._last_candle_minute: int = -1
        self._confirm_lock = _threading.Lock()

        # C1 fix: per-index dedup for OutcomeTracker registration.
        # Tracks the last alert_id registered per index so repeated 5-second
        # TradeSignals for the same trade don't create a new TradeOutcome row.
        self._last_registered_alert: dict = {}   # {index_name: alert_id}

        # B1 fix: thread guard — only one engine-eval thread at a time.
        self._eval_running = False
        self._eval_lock = _threading.Lock()

        # Option price history tracking: candle counter per alert_id.
        # Tracks how many candles have been recorded (stop after 10).
        self._opt_price_candle: dict = {}   # {alert_id: candle_num}

        # Outcome tracker — initialised before tabs so it rehydrates prior session
        from ml.outcome_tracker import OutcomeTracker
        from database.manager import get_db
        self._outcome_tracker = OutcomeTracker(
            db=get_db(),
            on_close=lambda oid, outcome: self._bridge.outcome_updated.emit(oid, outcome),
        )

        # Layer 1 auto trading — bracket orders via Fyers (+ paper mode)
        from trading.order_manager import OrderManager
        self._order_manager = OrderManager()
        # Give OrderManager access to OutcomeTracker so paper mode can
        # read live SL/T1/T2/T3 hits to compute simulated P&L
        self._order_manager.set_outcome_tracker(self._outcome_tracker)

        # S11 paper-trade monitor — created before _connect_signals so
        # on_alert is registered as a UI callback before sound fires.
        from engines.s11_monitor import S11Monitor
        from database.manager import get_db as _get_db
        self._s11_monitor = S11Monitor(db=_get_db())
        # Register on_alert as a UI callback — it runs synchronously before
        # the sound thread starts, setting alert_obj.is_s11 = True (Option A).
        self._am.add_ui_callback(self._s11_monitor.on_alert)

        self._setup_window()
        self._setup_tabs()
        self._setup_statusbar()
        self._connect_signals()
        self._start_timers()
        self._start_ml_pipeline()

        # Wire order manager to HQ trades tab (auto trading controls live there)
        self._hq_tab.set_order_manager(self._order_manager)

        # Wire ledger tab with DB and order manager
        from database.manager import get_db
        self._ledger_tab.set_db(get_db())
        self._ledger_tab.set_order_manager(self._order_manager)

        # Wire DB into order manager for paper trade persistence
        self._order_manager.set_db(get_db())

        # Wire S11 tab with its monitor
        self._s11_tab.set_monitor(self._s11_monitor)

    def _setup_window(self):
        self.setWindowTitle("NiftyTrader Intelligence  v2.0")
        self.resize(1700, 920)
        self.setMinimumSize(1300, 720)
        self.setStyleSheet(DARK_STYLE)

    def _setup_tabs(self):
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._cred_tab      = CredentialsTab(self._dm)
        self._dashboard_tab = DashboardTab(self._dm)
        self._scanner_tab   = ScannerTab(self._dm, self._sa)
        self._oc_tab        = OptionsFlowTab(self._dm)
        self._alerts_tab    = AlertsTab()
        self._hq_tab        = HQTradesTab()
        self._setup_tab     = SetupTab()
        self._ledger_tab    = LedgerTab()
        self._s11_tab       = S11Tab()
        self._ml_test_tab   = MLTestingTab()
        self._deploy_tab    = DeploymentControlPanel()

        self._tabs.addTab(self._cred_tab,      "🔑  CREDENTIALS")
        self._tabs.addTab(self._dashboard_tab, "📊  DASHBOARD")
        self._tabs.addTab(self._scanner_tab,   "🔍  SCANNER")
        self._tabs.addTab(self._oc_tab,        "📈  OPTIONS FLOW")
        self._tabs.addTab(self._alerts_tab,    "🚨  ALERTS")
        self._tabs.addTab(self._hq_tab,        "⭐  HQ TRADES")
        self._tabs.addTab(self._setup_tab,     "🎯  SETUPS")
        self._tabs.addTab(self._ledger_tab,    "📒  LEDGER")
        self._tabs.addTab(self._s11_tab,       "⚡  S11")
        self._tabs.addTab(self._ml_test_tab,   "🧠  ML TESTER")
        self._tabs.addTab(self._deploy_tab,    "🚀  DEPLOY")

        # Developer-only tab — hidden in client builds
        self._ml_report_tab = None
        if config.DEVELOPER_MODE:
            self._ml_report_tab = MLReportWidget()
            self._tabs.addTab(self._ml_report_tab, "🤖  ML REPORT")

        self.setCentralWidget(self._tabs)

    def _setup_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._sb_broker = QLabel("● BROKER: —")
        self._sb_ml     = QLabel("ML: —")
        self._sb_time   = QLabel()

        self._sb_broker.setStyleSheet("color:#f0883e; font-weight:bold;")
        self._sb_ml.setStyleSheet("color:#484f58;")
        self._sb_time.setStyleSheet("color:#8b949e;")

        self._status.addWidget(self._sb_broker)
        self._status.addWidget(self._sb_ml)
        self._status.addPermanentWidget(self._sb_time)

    def _connect_signals(self):
        self._bridge.data_updated.connect(self._on_data_updated)
        self._bridge.alert_received.connect(self._on_alert)
        self._bridge.model_updated.connect(self._on_model_updated)
        self._bridge.engine_result.connect(self._dashboard_tab.set_engine_result)
        self._bridge.outcome_updated.connect(self._alerts_tab.refresh_outcome)
        self._bridge.outcome_updated.connect(self._hq_tab.refresh_outcome)
        # Wire S11Monitor position-change callbacks → S11Tab refresh (thread-safe via signal)
        self._bridge.s11_position_changed.connect(self._s11_tab.refresh)
        self._s11_monitor._on_open  = lambda _: self._bridge.s11_position_changed.emit()
        self._s11_monitor._on_close = lambda _: self._bridge.s11_position_changed.emit()

        self._dm.add_update_callback(lambda: self._bridge.data_updated.emit())
        self._am.add_ui_callback(lambda a: self._bridge.alert_received.emit(a))
        self._cred_tab.connection_changed.connect(self._on_connection_changed)
        # Dashboard connect button → update status bar + feed back to dashboard
        self._dashboard_tab.connection_requested.connect(
            # I2 fix: use explicit non-empty check instead of bool(broker)
            lambda broker: self._on_connection_changed(broker != "", broker)
        )

    def _start_timers(self):
        # Clock — 2 s interval (halved UI redraws vs 1 s; clock precision is sufficient)
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(2000)

        # Engine evaluation — starts immediately, runs every DATA_FETCH_INTERVAL_SECONDS
        self._engine_timer = QTimer()
        self._engine_timer.timeout.connect(self._run_engines)
        self._engine_timer.start(config.DATA_FETCH_INTERVAL_SECONDS * 1000)

        # ML status bar — staggered 7 s after app start to avoid co-firing with
        # the engine timer; runs every 30 s (was 15 s — DB query is not time-critical)
        self._ml_status_timer = QTimer()
        self._ml_status_timer.timeout.connect(self._refresh_ml_status)
        QTimer.singleShot(7_000, lambda: self._ml_status_timer.start(30_000))

        # Auto trading: refresh order status from broker every 15 s
        # and update the positions panel on the dashboard.
        self._at_refresh_timer = QTimer()
        self._at_refresh_timer.timeout.connect(self._refresh_auto_trade)
        self._at_refresh_timer.start(15_000)

    def _start_ml_pipeline(self):
        """Start auto-labeler and model manager background loops."""
        import threading

        def _init():
            try:
                from ml.auto_labeler  import AutoLabeler
                from ml.model_manager import get_model_manager
                labeler = AutoLabeler()
                labeler.start()

                mm = get_model_manager()
                mm.add_update_callback(
                    lambda mv: self._bridge.model_updated.emit(mv)
                )
                mm.start_background_loop()
                logger.info("ML pipeline started")
            except Exception as e:
                logger.error(f"ML pipeline start error: {e}")

        threading.Thread(target=_init, daemon=True, name="MLInit").start()

    # ─── Slots ────────────────────────────────────────────────────

    @Slot()
    def _on_data_updated(self):
        tab = self._tabs.currentIndex()
        try:
            if   tab == 1: self._dashboard_tab.refresh()
            elif tab == 2: self._scanner_tab.refresh()
            elif tab == 3: self._oc_tab.refresh()
            elif tab == 7: self._ledger_tab.refresh()
        except Exception as e:
            logger.error(f"UI refresh error: {e}")

    @Slot()
    def _run_engines(self):
        # B1 fix: if the previous evaluation thread hasn't finished yet, skip this
        # tick entirely rather than spawning an unbounded stack of daemon threads.
        import threading
        with self._eval_lock:
            if self._eval_running:
                logger.debug("Engine eval skipped — previous tick still running")
                return
            self._eval_running = True

        def _eval():
            try:
                _eval_body()
            finally:
                with self._eval_lock:
                    self._eval_running = False

        def _eval_body():
            from engines.signal_aggregator import TradeSignal as _TS
            import dataclasses
            now = datetime.now()
            candle_minute = (now.hour * 60 + now.minute) // config.CANDLE_INTERVAL_MINUTES

            # Push VIX + cross-index directions to aggregator once per tick
            self._sa.set_vix(self._dm.get_vix())

            spot_prices  = {}
            option_ltps  = {}   # "INDEX:STRIKE:TYPE" → current option LTP
            _directions_this_tick: dict = {}
            for idx in config.INDICES:
                try:
                    df    = self._dm.get_df(idx)
                    chain = self._dm.get_option_chain(idx)
                    spot  = self._dm.get_spot(idx)

                    # Collect live option LTPs from already-fetched chain
                    if chain and chain.strikes:
                        for s in chain.strikes:
                            if s.call_ltp > 0:
                                option_ltps[f"{idx}:{int(s.strike)}:CE"] = s.call_ltp
                            if s.put_ltp > 0:
                                option_ltps[f"{idx}:{int(s.strike)}:PE"] = s.put_ltp
                    df_5m  = self._dm.get_df_5m(idx)
                    df_15m = self._dm.get_df_15m(idx)
                    prev_close       = self._dm.get_prev_close(idx)
                    futures_df       = self._dm.get_futures_df(idx)
                    preopen_gap_pct  = self._dm.get_preopen_gap_pct(idx)

                    if spot and spot > 0:
                        spot_prices[idx] = spot

                    # ── Signal aggregator (alert logic) ───────────────
                    alert = self._sa.evaluate(idx, df, chain, spot,
                                              df_5m=df_5m, df_15m=df_15m,
                                              prev_close=prev_close,
                                              futures_df=futures_df,
                                              preopen_gap_pct=preopen_gap_pct)
                    if alert:
                        self._am.fire(alert)
                        _directions_this_tick[idx] = alert.direction
                        # Buffer latest TradeSignal for candle-close confirmation
                        if isinstance(alert, _TS):
                            with self._confirm_lock:
                                self._pending_confirm[idx] = alert

                    # ── Engine stats for dashboard display ────────────
                    # Reuse the cached results from the aggregator's evaluate() call
                    # above — avoids re-instantiating and re-running all engines.
                    cached = self._sa.get_last_engine_results(idx)
                    if cached is not None:
                        mtf_r = cached["mtf_r"]
                        self._bridge.engine_result.emit(
                            idx,
                            cached["triggered"],
                            cached["conf"],
                            mtf_r.bias_5m,
                            mtf_r.bias_15m,
                            mtf_r.alignment,
                        )

                except Exception as e:
                    import traceback
                    logger.error(f"Engine error [{idx}]: {e}\n{traceback.format_exc()}")

            # Push cross-index directions collected this tick
            if _directions_this_tick:
                self._sa.set_cross_directions(_directions_this_tick)

            # Detect new candle before updating _last_candle_minute below
            _new_candle = (self._last_candle_minute != -1
                           and candle_minute != self._last_candle_minute)

            # ── Candle-close confirmation ──────────────────────────
            # When candle_minute changes, the previous candle just closed.
            # Fire one CONFIRMED copy of each buffered TradeSignal.
            with self._confirm_lock:
                if (self._last_candle_minute != -1
                        and candle_minute != self._last_candle_minute
                        and self._pending_confirm):
                    for _idx, _sig in self._pending_confirm.items():
                        try:
                            confirmed = dataclasses.replace(
                                _sig,
                                is_confirmed=True,
                                alert_type="CONFIRMED_SIGNAL",
                                timestamp=now,
                                alert_id=0,   # saved fresh in _on_alert
                            )
                            # S4 fix: route through AlertManager so it gets
                            # sound/popup/Telegram like any other alert.
                            # AlertManager callbacks post back to bridge → _on_alert.
                            self._am.fire(confirmed)
                            logger.info(
                                f"CONFIRMED signal emitted [{_idx}] "
                                f"{_sig.direction} on candle close"
                            )
                        except Exception as _e:
                            logger.error(f"Confirm emit error [{_idx}]: {_e}")
                    self._pending_confirm.clear()
                self._last_candle_minute = candle_minute

            # ── Tick outcome tracker with option LTPs ─────────────
            if spot_prices and self._outcome_tracker.tracking_count() > 0:
                try:
                    closed = self._outcome_tracker.tick(spot_prices, option_ltps)
                    # on_close callback already emits outcome_updated signal
                    _ = closed
                except Exception as e:
                    logger.error(f"OutcomeTracker tick error: {e}")
                # Save option LTP each candle for regression model training
                if _new_candle:
                    try:
                        self._save_option_price_history(option_ltps, now)
                    except Exception as e:
                        logger.error(f"Option price history save error: {e}")

            # ── Tick S11 paper-trade monitor ───────────────────────
            if spot_prices:
                try:
                    self._s11_monitor.tick(spot_prices, option_ltps)
                except Exception as e:
                    logger.error(f"S11Monitor tick error: {e}")

        try:
            threading.Thread(target=_eval, daemon=True).start()
        except Exception as e:
            logger.error(f"Engine thread spawn failed: {e}")
            with self._eval_lock:
                self._eval_running = False

    @Slot(object)
    def _on_alert(self, alert_obj):
        self._alerts_tab.add_alert(alert_obj)
        self._hq_tab.add_alert(alert_obj)  # only accepts TradeSignal instances

        from engines.signal_aggregator import TradeSignal
        is_confirmed = getattr(alert_obj, "is_confirmed", False)

        # Confirmed signals: DB save + setup alerts + outcome tracker + auto trade.
        # Runs in a daemon thread so DB writes don't block the GUI event loop.
        if is_confirmed and isinstance(alert_obj, TradeSignal):
            import threading as _threading
            _threading.Thread(
                target=self._process_confirmed_signal,
                args=(alert_obj,),
                daemon=True,
            ).start()

        # ── Layer 1 auto trade for non-confirmed signals ───────────
        # Only when AUTO_TRADE_CONFIRMED_ONLY is False (fires on raw TRADE_SIGNAL)
        if (isinstance(alert_obj, TradeSignal) and not is_confirmed
                and not config.AUTO_TRADE_CONFIRMED_ONLY
                and self._order_manager.is_enabled()):
            try:
                chain = self._dm.get_option_chain(
                    getattr(alert_obj, "index_name", ""))
                expiry = chain.expiry if chain else ""
                live_ltp = self._current_option_ltp(chain, alert_obj)
                self._order_manager.place_order(
                    alert_obj, expiry=expiry, live_ltp=live_ltp)
            except Exception as e:
                logger.error(f"AutoTrade (non-confirmed) place_order error: {e}")

        # Register ORIGINAL trade signals with outcome tracker (not confirmed copies).
        # C1 fix: only register once per unique alert_id per index — prevents a new
        # TradeOutcome row every 5 s for the same in-progress trade.
        if isinstance(alert_obj, TradeSignal) and not is_confirmed:
            aid = getattr(alert_obj, "alert_id", 0)
            idx = getattr(alert_obj, "index_name", "")
            if aid and aid != self._last_registered_alert.get(idx, 0):
                try:
                    self._outcome_tracker.register(alert_obj, aid)
                    self._last_registered_alert[idx] = aid
                except Exception as e:
                    logger.error(f"OutcomeTracker register error: {e}")

        # Log to scanner tab
        try:
            self._scanner_tab.add_log_row(
                idx          = alert_obj.index_name,
                alert_type   = alert_obj.alert_type,
                direction    = alert_obj.direction,
                engines_count= len(getattr(alert_obj, "engines_triggered", [])),
                confidence   = alert_obj.confidence_score,
                pcr          = getattr(alert_obj, "pcr", 0.0),
                atr          = getattr(alert_obj, "atr", 0.0),
            )
        except Exception as e:
            logger.debug(f"Scanner log row error: {e}")

    def _process_confirmed_signal(self, alert_obj):
        """Off-GUI-thread: DB save + outcome tracker + auto trade for confirmed signals."""
        try:
            from database.manager import get_db
            _db = get_db()
            cid = _db.save_alert({
                "index_name":        alert_obj.index_name,
                "timestamp":         alert_obj.timestamp,
                "alert_type":        "CONFIRMED_SIGNAL",
                "direction":         alert_obj.direction,
                "confidence_score":  alert_obj.confidence_score,
                "engines_triggered": alert_obj.engines_triggered,
                "engines_count":     len(alert_obj.engines_triggered),
                "spot_price":        alert_obj.spot_price,
                "atm_strike":        alert_obj.atm_strike,
                "pcr":               alert_obj.pcr,
                "atr":               alert_obj.atr,
                "suggested_instrument": alert_obj.suggested_instrument,
                "entry_reference":   alert_obj.entry_reference,
                "stop_loss_reference": alert_obj.stop_loss_reference,
                "target_reference":  alert_obj.target_reference,
                "raw_features":      getattr(alert_obj, "raw_features", {}),
            })
            alert_obj.alert_id = cid

            # Save setup_alerts for CONFIRMED_SIGNAL so per-setup stats
            # capture the highest-quality outcome (candle-close confirmed).
            try:
                _screener = self._sa._setup_screener
                _cached = self._sa.get_last_engine_results(alert_obj.index_name)
                if _cached and cid:
                    _conf_hits = _screener.evaluate(
                        index_name=alert_obj.index_name,
                        direction=alert_obj.direction,
                        timestamp=alert_obj.timestamp,
                        spot_price=alert_obj.spot_price,
                        atr=alert_obj.atr,
                        engines_count=len(getattr(alert_obj, "engines_triggered", [])),
                        di_r=_cached["di_r"],
                        vol_r=_cached["vol_r"],
                        oc_r=_cached["oc_r"],
                        regime_r=_cached["regime_r"],
                        vwap_r=_cached["vwap_r"],
                        mtf_r=_cached["mtf_r"],
                        pcr=alert_obj.pcr,
                    )
                    if _conf_hits:
                        _db.save_setup_alerts(_conf_hits, alert_id=cid)
            except Exception as _se:
                logger.debug(f"SetupScreener (confirmed) save failed: {_se}")

            # Register confirmed signal with outcome tracker so its row
            # gets WIN/LOSS/SL outcome instead of staying OPEN forever.
            try:
                self._outcome_tracker.register(alert_obj, cid)
            except Exception as e:
                logger.error(f"OutcomeTracker register (confirmed) error: {e}")

            # ── Layer 1 auto trading: place bracket order ──────
            if (config.AUTO_TRADE_CONFIRMED_ONLY
                    and self._order_manager.is_enabled()):
                try:
                    # Pass chain expiry AND current live option LTP so
                    # OrderManager uses the candle-close price, not the
                    # stale entry_reference from signal generation time.
                    chain = self._dm.get_option_chain(alert_obj.index_name)
                    expiry = chain.expiry if chain else ""
                    live_ltp = self._current_option_ltp(chain, alert_obj)
                    oid = self._order_manager.place_order(
                        alert_obj, expiry=expiry, live_ltp=live_ltp)
                    if oid:
                        logger.info(
                            f"Auto order placed [{alert_obj.index_name}] "
                            f"{alert_obj.direction} → {oid}"
                        )
                except Exception as e:
                    logger.error(f"AutoTrade place_order error: {e}")
        except Exception as e:
            logger.error(f"Confirmed signal DB save error: {e}")

        # Flash Alerts tab
        self._tabs.tabBar().setTabTextColor(4, QColor("#f85149"))
        QTimer.singleShot(
            config.ALERT_FLASH_DURATION_MS,
            lambda: self._tabs.tabBar().setTabTextColor(4, QColor("#8b949e"))
        )

        # Flash S11 tab and refresh when an S11 alert fires
        if getattr(alert_obj, "is_s11", False):
            _s11_idx = self._tabs.indexOf(self._s11_tab)
            if _s11_idx >= 0:
                self._tabs.tabBar().setTabTextColor(_s11_idx, QColor("#e3b341"))
                QTimer.singleShot(
                    config.ALERT_FLASH_DURATION_MS,
                    lambda: self._tabs.tabBar().setTabTextColor(_s11_idx, QColor("#8b949e"))
                )
            self._s11_tab.refresh()

    def _save_option_price_history(self, option_ltps: dict, now):
        """
        Called once per candle close for each open trade.
        Saves the current option LTP to option_price_history for regression training.
        Stops recording after 10 candles per trade.
        """
        from database.manager import get_db
        _db = get_db()

        open_states = self._outcome_tracker.get_open_states()

        for outcome_id, state in open_states.items():
            alert_id    = state.get("alert_id")
            opt_key     = state.get("opt_key")    # "INDEX:STRIKE:TYPE"
            entry_price = state.get("entry_price", 0.0)
            instr       = state.get("instrument") or opt_key or ""

            if not alert_id or not opt_key:
                continue

            candle_num = self._opt_price_candle.get(alert_id, 0)
            if candle_num >= 10:
                continue   # enough data collected for this trade

            ltp = option_ltps.get(opt_key, 0.0)
            if ltp <= 0:
                continue

            try:
                _db.save_option_price(
                    alert_id=alert_id,
                    instrument=instr,
                    timestamp=now,
                    ltp=ltp,
                    entry_price=entry_price,
                    candle_num=candle_num,
                )
                self._opt_price_candle[alert_id] = candle_num + 1
            except Exception as e:
                logger.error(f"save_option_price error alert_id={alert_id}: {e}")

    @Slot(object)
    def _on_model_updated(self, mv):
        self._sb_ml.setText(
            f"ML v{mv.version} — F1 {mv.metrics.get('f1', 0):.3f} "
            f"({mv.samples_used:,} samples)"
        )
        self._sb_ml.setStyleSheet("color:#3fb950; font-weight:bold;")
        logger.info(f"UI: model updated to v{mv.version}")

    @Slot(bool, str)
    def _on_connection_changed(self, connected: bool, broker: str):
        if connected:
            self._sb_broker.setText(f"● LIVE — {broker.upper()}")
            self._sb_broker.setStyleSheet("color:#3fb950; font-weight:bold;")
        else:
            self._sb_broker.setText("● DISCONNECTED")
            self._sb_broker.setStyleSheet("color:#f85149; font-weight:bold;")
        # Keep dashboard connection bar in sync
        self._dashboard_tab.on_connection_changed(connected, broker)

    @Slot()
    def _tick_clock(self):
        now = datetime.now()
        self._sb_time.setText(now.strftime("  %a %d %b %Y  |  %H:%M:%S  "))
        # Keep broker status in sync
        if self._dm.is_connected():
            if "DISCONNECTED" in self._sb_broker.text():
                self._sb_broker.setText(f"● LIVE — {config.BROKER.upper()}")
                self._sb_broker.setStyleSheet("color:#3fb950; font-weight:bold;")

    @Slot()
    def _refresh_auto_trade(self):
        """Poll broker for order updates and refresh the positions panel."""
        try:
            import threading
            threading.Thread(
                target=self._order_manager.refresh_order_status,
                daemon=True, name="ATRefresh"
            ).start()
        except Exception:
            pass
        # Update UI on main thread (timer fires on main thread already)
        try:
            self._hq_tab.refresh_positions()
        except Exception as e:
            logger.debug(f"AT positions refresh error: {e}")

    @Slot()
    def _refresh_ml_status(self):
        try:
            from ml.model_manager import get_model_manager
            s = get_model_manager().get_status()
            if s["phase"] == 1:
                need = s["needed_to_train"]
                self._sb_ml.setText(f"ML: collecting ({need} samples needed)")
                self._sb_ml.setStyleSheet("color:#8b949e;")
            elif s["has_model"]:
                v = s["model_version"]
                self._sb_ml.setText(f"ML v{v} active — {s['labeled_samples']:,} samples")
                self._sb_ml.setStyleSheet("color:#3fb950;")
        except Exception:
            pass

    def _current_option_ltp(self, chain, signal) -> float:
        """
        Return the live option LTP for the strike/type on the signal.
        Used so order placement uses the candle-close price, not the
        stale entry_reference that was set at signal-generation time.
        Falls back to signal.entry_reference if chain data is unavailable.
        """
        if chain is None or not chain.strikes:
            return float(getattr(signal, "entry_reference", 0) or 0)
        strike      = float(getattr(signal, "strike", 0) or 0)
        option_type = getattr(signal, "option_type", "CE") or "CE"
        if strike <= 0:
            return float(getattr(signal, "entry_reference", 0) or 0)
        for s in chain.strikes:
            if s.strike == strike:
                ltp = s.call_ltp if option_type == "CE" else s.put_ltp
                if ltp and ltp > 0:
                    return float(ltp)
                break
        # Strike found but LTP is 0 (illiquid) — fall back to entry_reference
        return float(getattr(signal, "entry_reference", 0) or 0)

    def closeEvent(self, event):
        self._dm.stop()
        event.accept()
