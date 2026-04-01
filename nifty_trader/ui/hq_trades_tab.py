"""
ui/hq_trades_tab.py
High Quality Trades Tab — shows only TRADE_SIGNAL and CONFIRMED_SIGNAL alerts.

Filters by ML score threshold (0 = all pass, 70 = ML-confident only).
Displays entry, SL, and targets prominently.
As the ML model matures, raise the threshold to surface only A-grade setups.
"""

from datetime import date, datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QSlider, QSpinBox, QDoubleSpinBox, QSplitter, QTextEdit,
    QSizePolicy, QPushButton, QMessageBox, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor

import config
from database.manager import get_db


# ── helpers ───────────────────────────────────────────────────────

def _item(text, color="#c9d1d9", bold=False, center=True, bg=None):
    it = QTableWidgetItem(str(text))
    it.setForeground(QColor(color))
    if bold:
        f = it.font(); f.setBold(True); it.setFont(f)
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    if bg:
        it.setBackground(QColor(bg))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


def _lbl(text="", color="#c9d1d9", bold=False, size=11):
    w = QLabel(text)
    w.setStyleSheet(
        f"color:{color}; font-size:{size}px;" + (" font-weight:bold;" if bold else "")
    )
    return w


def _stat_widget(parent_layout, label):
    f = QFrame()
    ly = QVBoxLayout(f)
    ly.setContentsMargins(8, 0, 16, 0)
    ly.setSpacing(1)
    ly.addWidget(_lbl(label, "#8b949e", size=9))
    v = _lbl("—", "#e6edf3", bold=True, size=13)
    ly.addWidget(v)
    parent_layout.addWidget(f)
    return v


# ─────────────────────────────────────────────────────────────────
# TRADE DETAIL PANEL (right side)
# ─────────────────────────────────────────────────────────────────

class HQDetailPanel(QWidget):
    """Right-side panel showing entry / SL / targets and ML breakdown."""

    def __init__(self):
        super().__init__()
        ly = QVBoxLayout(self)
        ly.setContentsMargins(8, 8, 8, 8)
        ly.setSpacing(6)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            "QTextEdit { background:#0d1117; color:#c9d1d9; "
            "border:1px solid #30363d; border-radius:4px; font-size:11px; }"
        )
        ly.addWidget(self._text)
        self._text.setPlainText("Select a row to see trade details.")

    def show_trade(self, alert_obj):
        if alert_obj is None:
            self._text.setPlainText("No trade selected.")
            return

        ml   = getattr(alert_obj, "ml_prediction", None)
        ml_ok = ml is not None and ml.is_available

        is_confirmed = getattr(alert_obj, "is_confirmed", False)
        atype = "✅ CONFIRMED" if is_confirmed else "🎯 TRADE SIGNAL"
        dc    = "🟢 BULLISH" if alert_obj.direction == "BULLISH" else "🔴 BEARISH"

        import config as _cfg
        entry  = getattr(alert_obj, "entry_reference",    0.0) or 0.0
        sl     = getattr(alert_obj, "stop_loss_reference", 0.0) or 0.0
        tgt    = getattr(alert_obj, "target_reference",   0.0) or 0.0
        t1     = getattr(alert_obj, "target1",  tgt) or tgt
        t2     = getattr(alert_obj, "target2",  0.0) or 0.0
        t3     = getattr(alert_obj, "target3",  0.0) or 0.0
        instr  = getattr(alert_obj, "suggested_instrument", "—") or "—"
        eng_list = getattr(alert_obj, "engines_triggered", []) or []

        lot_size = _cfg.SYMBOL_MAP.get(alert_obj.index_name, {}).get("lot_size", 1)
        invest   = round(entry * lot_size, 2) if entry > 0 else 0.0
        pnl_sl   = round((sl - entry) * lot_size, 2) if entry > 0 and sl > 0 else 0.0
        pnl_t1   = round((t1 - entry) * lot_size, 2) if entry > 0 and t1 > 0 else 0.0
        pnl_t2   = round((t2 - entry) * lot_size, 2) if entry > 0 and t2 > 0 else 0.0
        pnl_t3   = round((t3 - entry) * lot_size, 2) if entry > 0 and t3 > 0 else 0.0

        def _pnl(v):
            return f"₹{v:+,.0f}" if v != 0 else "—"

        lines = [
            f"{'─' * 42}",
            f"  {atype}  |  {dc}",
            f"  {alert_obj.index_name}  @  {alert_obj.spot_price:.2f}",
            f"  {alert_obj.timestamp.strftime('%H:%M:%S  %d-%b-%Y')}",
            f"{'─' * 42}",
            f"  INSTRUMENT : {instr}",
            f"  LOT SIZE   : {lot_size}",
            f"  INVESTMENT : ₹{invest:,.0f}" if invest > 0 else "  INVESTMENT : —",
            f"  ENTRY      : {entry:.2f}",
            f"  STOP LOSS  : {sl:.2f}  ({_pnl(pnl_sl)})",
            f"  TARGET 1   : {t1:.2f}  ({_pnl(pnl_t1)})",
        ]
        if t2:
            lines.append(f"  TARGET 2   : {t2:.2f}  ({_pnl(pnl_t2)})")
        if t3:
            lines.append(f"  TARGET 3   : {t3:.2f}  ({_pnl(pnl_t3)})")

        lines += [
            f"{'─' * 42}",
            f"  STRATEGY SCORE : {alert_obj.confidence_score:.1f}%",
        ]

        if ml_ok:
            lines += [
                f"  ML SCORE       : {ml.ml_confidence:.1f}%  ({ml.recommendation})",
                f"  ML MODEL       : v{ml.model_version}  ({ml.samples_used} samples)",
                f"  COMBINED       : {(alert_obj.confidence_score + ml.ml_confidence) / 2:.1f}%",
            ]
            if ml.top_features:
                lines.append(f"{'─' * 42}")
                lines.append("  TOP ML FEATURES :")
                for feat, imp in sorted(ml.top_features.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"    {feat:<28} {imp:.3f}")
        else:
            lines.append("  ML SCORE       : not yet available")

        lines += [
            f"{'─' * 42}",
            f"  ENGINES ({len(eng_list)}/7) :",
            "    " + ", ".join(eng_list) if eng_list else "    —",
        ]

        self._text.setPlainText("\n".join(lines))


# ─────────────────────────────────────────────────────────────────
# HQ TRADES TAB
# ─────────────────────────────────────────────────────────────────

class HQTradesTab(QWidget):
    """
    High-Quality Trades tab.
    Shows TRADE_SIGNAL and CONFIRMED_SIGNAL alerts, filtered by ML threshold.
    """

    # Columns: TIME INDEX TYPE DIR S% M% C% ENG INSTRUMENT ENTRY SL T1 T2 T3 OUTCOME
    _COLS = [
        "TIME", "INDEX", "TYPE", "DIR",
        "S%", "M%", "C%", "ENG",
        "INSTRUMENT", "ENTRY", "SL", "T1", "T2", "T3",
        "OUTCOME",
    ]

    def __init__(self):
        super().__init__()
        self._db = get_db()
        self._ml_threshold = 0       # 0 = all pass (grow with model maturity)
        self._row_alerts: dict = {}  # {row_idx: alert_obj}
        self._order_manager = None   # set by main_window after init
        self._setup_ui()
        self._load_history()

    # ── UI BUILD ──────────────────────────────────────────────────

    def _setup_ui(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(8, 8, 8, 8)
        ly.setSpacing(6)

        # ── Header ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = _lbl("HIGH QUALITY TRADES", "#e6edf3", bold=True, size=13)
        hdr.addWidget(title)
        hdr.addSpacing(20)
        hdr.addWidget(_lbl("ML THRESHOLD:", "#8b949e", size=10))

        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 95)
        self._threshold_spin.setValue(0)
        self._threshold_spin.setSuffix("%")
        self._threshold_spin.setFixedWidth(70)
        self._threshold_spin.setStyleSheet(
            "QSpinBox { background:#161b22; color:#c9d1d9; border:1px solid #30363d;"
            " border-radius:3px; padding:2px 4px; font-size:11px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width:16px; }"
        )
        self._threshold_spin.valueChanged.connect(self._on_threshold_changed)
        hdr.addWidget(self._threshold_spin)

        self._threshold_lbl = _lbl("(all signals pass)", "#484f58", size=10)
        hdr.addWidget(self._threshold_lbl)
        hdr.addStretch()

        btn_clear = QPushButton("CLEAR")
        btn_clear.setFixedHeight(26)
        btn_clear.setStyleSheet(
            "QPushButton { background:#21262d; color:#8b949e; border:1px solid #30363d;"
            " border-radius:4px; padding:4px 10px; }"
            "QPushButton:hover { background:#30363d; color:#c9d1d9; }"
        )
        btn_clear.clicked.connect(self._clear)
        hdr.addWidget(btn_clear)
        ly.addLayout(hdr)

        # ── Auto Trading bar ──────────────────────────────────────
        at_bar = QFrame()
        at_bar.setObjectName("ATBar")
        at_bar.setStyleSheet(
            "#ATBar { background:#161b22; border:1px solid #30363d; border-radius:4px; }"
        )
        at_ly = QHBoxLayout(at_bar)
        at_ly.setContentsMargins(14, 6, 14, 6)
        at_ly.setSpacing(16)

        at_ly.addWidget(_lbl("AUTO TRADING", "#8b949e", bold=True, size=11))
        self._at_status_lbl  = _lbl("● OFF", "#484f58", bold=True, size=11)
        self._at_summary_lbl = _lbl("Orders: 0/3  |  P&L: ₹0.00", "#484f58", size=10)
        at_ly.addWidget(self._at_status_lbl)
        at_ly.addStretch()
        at_ly.addWidget(self._at_summary_lbl)

        _btn_off_ss = (
            "QPushButton { background:#21262d; color:#8b949e; border:1px solid #30363d;"
            " padding:3px 14px; border-radius:3px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#30363d; color:#c9d1d9; }"
        )
        self._at_paper_btn = QPushButton("📋  Paper Trade")
        self._at_paper_btn.setFixedHeight(26)
        self._at_paper_btn.setStyleSheet(_btn_off_ss)
        self._at_paper_btn.clicked.connect(self._on_paper_btn_clicked)

        self._at_live_btn = QPushButton("⚡  Live Trade")
        self._at_live_btn.setFixedHeight(26)
        self._at_live_btn.setStyleSheet(_btn_off_ss)
        self._at_live_btn.clicked.connect(self._on_live_btn_clicked)

        self._at_halt_btn = QPushButton("🛑  HALT")
        self._at_halt_btn.setFixedHeight(26)
        self._at_halt_btn.setStyleSheet(_btn_off_ss)
        self._at_halt_btn.clicked.connect(self._on_halt_btn_clicked)

        at_ly.addWidget(self._at_paper_btn)
        at_ly.addWidget(self._at_live_btn)
        at_ly.addWidget(self._at_halt_btn)
        ly.addWidget(at_bar)

        # ── Trade Settings bar ────────────────────────────────────
        ts_bar = QFrame()
        ts_bar.setObjectName("TSBar")
        ts_bar.setStyleSheet(
            "#TSBar { background:#0d1117; border:1px solid #21262d; border-radius:4px; }"
        )
        ts_ly = QHBoxLayout(ts_bar)
        ts_ly.setContentsMargins(14, 5, 14, 5)
        ts_ly.setSpacing(18)

        _spin_ss = (
            "QDoubleSpinBox, QSpinBox {"
            "  background:#161b22; color:#c9d1d9; border:1px solid #30363d;"
            "  border-radius:3px; padding:1px 4px; font-size:11px;"
            "}"
            "QDoubleSpinBox:focus, QSpinBox:focus { border:1px solid #58a6ff; }"
        )
        _radio_ss = "QRadioButton { color:#8b949e; font-size:11px; }"

        # ── Max Loss section ──────────────────────────────────────
        ts_ly.addWidget(_lbl("MAX LOSS:", "#8b949e", bold=True, size=10))

        self._loss_rbr = QRadioButton("₹")
        self._loss_rbr.setStyleSheet(_radio_ss)
        self._loss_rbp = QRadioButton("%")
        self._loss_rbp.setStyleSheet(_radio_ss)
        self._loss_mode_grp = QButtonGroup(self)
        self._loss_mode_grp.addButton(self._loss_rbr, 0)   # id 0 = ₹ mode
        self._loss_mode_grp.addButton(self._loss_rbp, 1)   # id 1 = % mode
        self._loss_rbr.setChecked(True)

        self._loss_rs = QDoubleSpinBox()
        self._loss_rs.setRange(100, 5_000_000)
        self._loss_rs.setDecimals(0)
        self._loss_rs.setSingleStep(500)
        self._loss_rs.setValue(config.AUTO_TRADE_MAX_DAILY_LOSS)
        self._loss_rs.setFixedWidth(88)
        self._loss_rs.setStyleSheet(_spin_ss)
        self._loss_rs.setToolTip("Maximum loss in ₹ before trading stops for the day")

        self._loss_ps = QDoubleSpinBox()
        self._loss_ps.setRange(0.1, 100.0)
        self._loss_ps.setDecimals(1)
        self._loss_ps.setSingleStep(0.5)
        self._loss_ps.setFixedWidth(64)
        self._loss_ps.setStyleSheet(_spin_ss)
        self._loss_ps.setToolTip("Maximum loss as % of capital before trading stops")
        # compute initial pct from config
        _init_pct = round(
            config.AUTO_TRADE_MAX_DAILY_LOSS / max(1, config.DEFAULT_CAPITAL) * 100, 1
        )
        self._loss_ps.setValue(_init_pct)
        self._loss_ps.setEnabled(False)   # ₹ mode active by default

        self._loss_equiv_lbl = _lbl(
            f"of ₹{config.DEFAULT_CAPITAL/100_000:.0f}L capital", "#484f58", size=10
        )

        ts_ly.addWidget(self._loss_rbr)
        ts_ly.addWidget(self._loss_rs)
        ts_ly.addWidget(self._loss_rbp)
        ts_ly.addWidget(self._loss_ps)
        ts_ly.addWidget(self._loss_equiv_lbl)

        # ── Separator ─────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#30363d;")
        ts_ly.addWidget(sep)

        # ── Lots section ──────────────────────────────────────────
        ts_ly.addWidget(_lbl("LOTS:", "#8b949e", bold=True, size=10))

        self._lots_spin = QSpinBox()
        self._lots_spin.setRange(1, 50)
        self._lots_spin.setValue(max(1, config.AUTO_TRADE_FIXED_LOTS))
        self._lots_spin.setFixedWidth(60)
        self._lots_spin.setStyleSheet(_spin_ss)
        self._lots_spin.setToolTip("Number of lots per trade")
        ts_ly.addWidget(self._lots_spin)

        self._lots_qty_lbl = _lbl("", "#484f58", size=10)
        ts_ly.addWidget(self._lots_qty_lbl)

        ts_ly.addStretch()
        ly.addWidget(ts_bar)

        # Wire signals — do this after all widgets are created
        self._loss_mode_grp.idToggled.connect(self._on_loss_mode_toggled)
        self._loss_rs.valueChanged.connect(self._on_loss_rs_changed)
        self._loss_ps.valueChanged.connect(self._on_loss_ps_changed)
        self._lots_spin.valueChanged.connect(self._on_lots_changed)

        # ── Main splitter ─────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Left — table
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._COLS))
        self._table.setHorizontalHeaderLabels(self._COLS)
        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(QHeaderView.Stretch)
        for i in (0, 4, 5, 6, 7, 14):
            hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_select)
        self._table.setStyleSheet(
            "QTableWidget { background:#0d1117; color:#c9d1d9; "
            "gridline-color:#21262d; border:1px solid #30363d; }"
            "QHeaderView::section { background:#161b22; color:#8b949e; "
            "border:none; padding:4px; font-size:10px; }"
        )
        splitter.addWidget(self._table)

        # Right — detail panel
        self._detail = HQDetailPanel()
        self._detail.setMinimumWidth(320)
        splitter.addWidget(self._detail)
        splitter.setSizes([1100, 380])
        ly.addWidget(splitter)

        # ── Stats bar ─────────────────────────────────────────────
        sb_frame = QFrame()
        sb_frame.setStyleSheet(
            "background:#161b22; border:1px solid #30363d; border-radius:3px;"
        )
        sb = QHBoxLayout(sb_frame)
        sb.setContentsMargins(12, 6, 12, 6)
        self._s_total    = _stat_widget(sb, "SIGNALS TODAY")
        self._s_conf     = _stat_widget(sb, "CONFIRMED")
        self._s_winrate  = _stat_widget(sb, "WIN RATE")
        self._s_avg_ml   = _stat_widget(sb, "AVG ML SCORE")
        self._s_filtered = _stat_widget(sb, "ML FILTERED OUT")
        sb.addStretch()
        ly.addWidget(sb_frame)

        # ── Open Positions panel ──────────────────────────────────
        pos_panel = QFrame()
        pos_panel.setObjectName("PosPanel")
        pos_panel.setStyleSheet(
            "#PosPanel { background:#161b22; border:1px solid #30363d; border-radius:4px; }"
        )
        pos_ly = QVBoxLayout(pos_panel)
        pos_ly.setContentsMargins(12, 8, 12, 8)
        pos_ly.setSpacing(6)

        pos_hdr = QHBoxLayout()
        pos_hdr.addWidget(_lbl("OPEN POSITIONS", "#58a6ff", bold=True, size=12))
        pos_hdr.addStretch()
        self._pos_count_lbl = _lbl("0 orders", "#484f58", size=10)
        pos_hdr.addWidget(self._pos_count_lbl)
        pos_ly.addLayout(pos_hdr)

        _POS_COLS = ["SYMBOL", "QTY", "ENTRY", "SL OFFSET", "TP OFFSET", "STATUS", "PLACED AT"]
        self._pos_table = QTableWidget(0, len(_POS_COLS))
        self._pos_table.setHorizontalHeaderLabels(_POS_COLS)
        self._pos_table.verticalHeader().setVisible(False)
        self._pos_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._pos_table.setSelectionMode(QTableWidget.NoSelection)
        self._pos_table.setFocusPolicy(Qt.NoFocus)
        self._pos_table.setShowGrid(False)
        self._pos_table.setStyleSheet(
            "QTableWidget { background:#0d1117; color:#c9d1d9; font-size:11px; border:none; }"
            "QHeaderView::section { background:#161b22; color:#8b949e; font-size:10px;"
            " font-weight:bold; border:none; border-bottom:1px solid #30363d; padding:3px 6px; }"
            "QTableWidget::item { padding:3px 6px; border-bottom:1px solid #21262d; }"
        )
        hh = self._pos_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(_POS_COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._pos_table.setFixedHeight(26 + 3 * 28)   # header + up to 3 rows visible
        pos_ly.addWidget(self._pos_table)
        ly.addWidget(pos_panel)

    # ── PUBLIC API ────────────────────────────────────────────────

    def set_order_manager(self, om):
        """Called by main_window after OrderManager is initialised."""
        self._order_manager = om
        # Push current UI values into the backend
        self._apply_loss_setting()
        self._apply_lots_setting()
        self._refresh_auto_trade_bar()
        self.refresh_positions()

    # ── Trade settings controls ────────────────────────────────────

    def _on_loss_mode_toggled(self, btn_id: int, checked: bool):
        """Switch between ₹ and % max-loss input modes."""
        if not checked:
            return
        is_pct = (btn_id == 1)
        self._loss_rs.setEnabled(not is_pct)
        self._loss_ps.setEnabled(is_pct)
        if is_pct:
            self._loss_equiv_lbl.setText(
                f"of ₹{config.DEFAULT_CAPITAL/100_000:.0f}L  "
                f"≡ ₹{self._loss_ps.value() * config.DEFAULT_CAPITAL / 100:,.0f}"
            )
        else:
            pct = self._loss_rs.value() / config.DEFAULT_CAPITAL * 100
            self._loss_equiv_lbl.setText(
                f"≡ {pct:.1f}% of ₹{config.DEFAULT_CAPITAL/100_000:.0f}L capital"
            )
        self._apply_loss_setting()

    def _on_loss_rs_changed(self, value: float):
        """₹ input changed — sync pct label and push to backend."""
        # Sync % input silently (block its signal to avoid ping-pong)
        self._loss_ps.blockSignals(True)
        self._loss_ps.setValue(round(value / config.DEFAULT_CAPITAL * 100, 1))
        self._loss_ps.blockSignals(False)
        pct = value / config.DEFAULT_CAPITAL * 100
        self._loss_equiv_lbl.setText(
            f"≡ {pct:.1f}% of ₹{config.DEFAULT_CAPITAL/100_000:.0f}L capital"
        )
        self._apply_loss_setting()

    def _on_loss_ps_changed(self, value: float):
        """% input changed — sync ₹ label and push to backend."""
        rupees = value * config.DEFAULT_CAPITAL / 100
        self._loss_rs.blockSignals(True)
        self._loss_rs.setValue(round(rupees))
        self._loss_rs.blockSignals(False)
        self._loss_equiv_lbl.setText(
            f"of ₹{config.DEFAULT_CAPITAL/100_000:.0f}L  ≡ ₹{rupees:,.0f}"
        )
        self._apply_loss_setting()

    def _apply_loss_setting(self):
        """Push current max-loss value to OrderManager."""
        if self._order_manager is None:
            return
        self._order_manager.set_max_daily_loss(self._loss_rs.value())

    def _on_lots_changed(self, value: int):
        """Lots spin changed — update qty label and push to backend."""
        self._update_lots_qty_label(value)
        if self._order_manager is None:
            return
        self._order_manager.set_fixed_lots(value)

    def _apply_lots_setting(self):
        """Push current lots value to OrderManager."""
        if self._order_manager is None:
            return
        lots = self._lots_spin.value()
        self._order_manager.set_fixed_lots(lots)
        self._update_lots_qty_label(lots)

    def _update_lots_qty_label(self, lots: int):
        """Show e.g. '1 lot = 65 qty (NIFTY)'."""
        # Show smallest-lot-size index as a hint
        hint = ""
        for name, sym in config.SYMBOL_MAP.items():
            ls = sym.get("lot_size", 0)
            if ls:
                hint = f"= {lots * ls} qty ({name})"
                break
        self._lots_qty_lbl.setText(hint)

    # ── Auto trading controls ──────────────────────────────────────

    def _on_paper_btn_clicked(self):
        if self._order_manager is None:
            return
        new_mode = "OFF" if self._order_manager.get_mode() == "PAPER" else "PAPER"
        self._order_manager.set_mode(new_mode)
        self._refresh_auto_trade_bar()

    def _on_halt_btn_clicked(self):
        if self._order_manager is None:
            return
        from trading.order_manager import OrderManager
        if OrderManager.is_halted():
            # Already halted — clear halt
            OrderManager.set_halt(False)
        else:
            # Activate halt — confirm first
            msg = QMessageBox(self)
            msg.setWindowTitle("Activate Trading Halt")
            msg.setIcon(QMessageBox.Critical)
            msg.setText(
                "<b>Activate TRADING HALT?</b><br><br>"
                "All order placement will be blocked immediately.<br>"
                "The halt persists across app restarts until you clear it.<br><br>"
                "Use this in emergencies (circuit breaker, wrong signal, etc.)"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec() == QMessageBox.Yes:
                OrderManager.set_halt(True)
        self._refresh_auto_trade_bar()

    def _on_live_btn_clicked(self):
        if self._order_manager is None:
            return
        # Turning LIVE off — no confirmation needed
        if self._order_manager.get_mode() == "LIVE":
            self._order_manager.set_mode("OFF")
            self._refresh_auto_trade_bar()
            return
        # Turning LIVE on — require explicit confirmation
        msg = QMessageBox(self)
        msg.setWindowTitle("Activate LIVE Trading")
        msg.setIcon(QMessageBox.Warning)
        msg.setText(
            "<b>You are about to enable LIVE trading.</b><br><br>"
            "Real bracket orders will be placed at the exchange.<br>"
            "Real money is at risk.<br><br>"
            f"Daily cap: <b>{config.AUTO_TRADE_MAX_DAILY_ORDERS} orders</b> &nbsp;|&nbsp; "
            f"Min confidence: <b>{config.AUTO_TRADE_MIN_CONFIDENCE}%</b> &nbsp;|&nbsp; "
            f"Min engines: <b>{config.AUTO_TRADE_MIN_ENGINES}</b><br><br>"
            "Are you sure?"
        )
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        if msg.exec() == QMessageBox.Yes:
            self._order_manager.set_live_mode(True)
            self._refresh_auto_trade_bar()

    def _refresh_auto_trade_bar(self):
        """Update button styles and summary line to match current mode."""
        if self._order_manager is None:
            return
        mode    = self._order_manager.get_mode()
        summary = self._order_manager.get_today_summary()

        _off = (
            "QPushButton { background:#21262d; color:#8b949e; border:1px solid #30363d;"
            " padding:3px 14px; border-radius:3px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#30363d; color:#c9d1d9; }"
        )
        _paper_on = (
            "QPushButton { background:#3d3000; color:#f0883e; border:1px solid #7d5a00;"
            " padding:3px 14px; border-radius:3px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#5a4200; color:#ffa94d; }"
        )
        _live_on = (
            "QPushButton { background:#3d0000; color:#f85149; border:1px solid #6e1b1b;"
            " padding:3px 14px; border-radius:3px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#6e1b1b; color:#ff7b7b; }"
        )

        if mode == "PAPER":
            self._at_status_lbl.setText("● PAPER")
            self._at_status_lbl.setStyleSheet("color:#f0883e; font-weight:bold; font-size:11px;")
            self._at_paper_btn.setText("✕  Stop Paper Trade")
            self._at_paper_btn.setStyleSheet(_paper_on)
            self._at_live_btn.setText("⚡  Go Live")
            self._at_live_btn.setStyleSheet(_off)
        elif mode == "LIVE":
            self._at_status_lbl.setText("● LIVE")
            self._at_status_lbl.setStyleSheet("color:#f85149; font-weight:bold; font-size:11px;")
            self._at_paper_btn.setText("📋  Paper Trade")
            self._at_paper_btn.setStyleSheet(_off)
            self._at_live_btn.setText("✕  Stop Live Trade")
            self._at_live_btn.setStyleSheet(_live_on)
        else:
            self._at_status_lbl.setText("● OFF")
            self._at_status_lbl.setStyleSheet("color:#484f58; font-weight:bold; font-size:11px;")
            self._at_paper_btn.setText("📋  Paper Trade")
            self._at_paper_btn.setStyleSheet(_off)
            self._at_live_btn.setText("⚡  Live Trade")
            self._at_live_btn.setStyleSheet(_off)

        # ── HALT button state ──────────────────────────────────────
        from trading.order_manager import OrderManager as _OM
        _halt_on = (
            "QPushButton { background:#4d0000; color:#ff4444; border:2px solid #ff2222;"
            " padding:3px 14px; border-radius:3px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#6e0000; color:#ff7777; }"
        )
        if _OM.is_halted():
            self._at_halt_btn.setText("✅  Clear Halt")
            self._at_halt_btn.setStyleSheet(_halt_on)
        else:
            self._at_halt_btn.setText("🛑  HALT")
            self._at_halt_btn.setStyleSheet(_off)

        pnl          = summary.get("pnl", 0.0)
        placed       = summary.get("placed", 0)
        cap          = summary.get("cap", 3)
        wins         = summary.get("wins", 0)
        losses_count = summary.get("losses", 0)
        loss_cap_hit = summary.get("loss_cap_hit", False)
        loss_cap     = summary.get("loss_cap", config.AUTO_TRADE_MAX_DAILY_LOSS)
        sign         = "+" if pnl >= 0 else ""
        pnl_color    = "#3fb950" if pnl > 0 else "#f85149" if pnl < 0 else "#484f58"

        if _OM.is_halted():
            tag_color = "#ff4444"
            tag       = "  ⛔ HALTED"
        elif loss_cap_hit:
            tag_color = "#f85149"
            tag       = f"  ⛔ LOSS CAP ₹{loss_cap:,.0f} HIT"
        else:
            tag_color = pnl_color if placed > 0 else "#484f58"
            tag       = ""

        w_l = f"  W:{wins} L:{losses_count}" if placed > 0 else ""
        self._at_summary_lbl.setText(
            f"Orders: {placed}/{cap}{w_l}  |  P&L: {sign}₹{pnl:,.2f}{tag}"
        )
        self._at_summary_lbl.setStyleSheet(
            f"color:{tag_color}; font-size:10px;"
        )

    def refresh_positions(self):
        """Refresh the open positions table from OrderManager."""
        if self._order_manager is None:
            return
        orders = self._order_manager.get_open_orders()
        self._pos_count_lbl.setText(f"{len(orders)} order{'s' if len(orders) != 1 else ''}")
        self._pos_table.setRowCount(len(orders))
        for row, rec in enumerate(orders):
            placed_str = rec.get("placed_at")
            if isinstance(placed_str, datetime):
                placed_str = placed_str.strftime("%H:%M:%S")
            status = rec.get("status", "OPEN")
            mode   = rec.get("mode", "LIVE")
            pnl    = rec.get("pnl", 0.0)
            pnl_str = f"{'+' if pnl >= 0 else ''}{pnl:,.0f}"

            if "T1" in status or "T2" in status or "T3" in status or status == "FILLED":
                sc = "#3fb950"
            elif "SL" in status:
                sc = "#f85149"
            elif "OPEN" in status:
                sc = "#f0883e"
            else:
                sc = "#8b949e"

            mode_badge = "[P]" if mode == "PAPER" else "[L]"
            cells = [
                (f"{mode_badge} {rec.get('symbol', '')}", "#c9d1d9"),
                (str(rec.get("qty", "")), "#e6edf3"),
                (f"{rec.get('entry', 0):.1f}", "#58a6ff"),
                (f"{rec.get('sl', 0):.1f}", "#f85149"),
                (f"{rec.get('tp', 0):.1f}", "#3fb950"),
                (status, sc),
                (f"{placed_str}  {pnl_str}", "#8b949e"),
            ]
            for col, (text, color) in enumerate(cells):
                self._pos_table.setItem(row, col, _item(text, color))
        self._refresh_auto_trade_bar()

    def add_alert(self, alert_obj):
        """Called from main_window._on_alert() for every TRADE/CONFIRMED alert."""
        from engines.signal_aggregator import TradeSignal
        if not isinstance(alert_obj, TradeSignal):
            return  # only show trade-grade alerts

        ml     = getattr(alert_obj, "ml_prediction", None)
        ml_ok  = ml is not None and ml.is_available
        ml_pct = ml.ml_confidence if ml_ok else 0.0

        # Apply ML threshold filter — if ML not ready, let all through
        if ml_ok and ml_pct < self._ml_threshold:
            self._update_stats()
            return

        self._insert_row(alert_obj, ml_pct, ml_ok)
        self._update_stats()

    def refresh_outcome(self, outcome_id: int, outcome_str: str = ""):
        """Sync outcome column when OutcomeTracker closes a trade."""
        try:
            with self._db.get_session() as session:
                from database.models import TradeOutcome
                outcome = session.query(TradeOutcome).filter(
                    TradeOutcome.id == outcome_id
                ).first()
                if not outcome:
                    return
                badge, color = self._outcome_badge(outcome)
                aid = outcome.alert_id

            for row_idx, ao in self._row_alerts.items():
                if getattr(ao, "alert_id", None) == aid:
                    self._table.setItem(row_idx, 14, _item(badge, color, bold=True))
                    break
            self._update_stats()
        except Exception:
            pass

    # ── PRIVATE ───────────────────────────────────────────────────

    def _insert_row(self, alert_obj, ml_pct, ml_ok):
        r = 0
        self._table.insertRow(r)
        self._row_alerts = {k + 1: v for k, v in self._row_alerts.items()}
        self._row_alerts[0] = alert_obj

        is_confirmed = getattr(alert_obj, "is_confirmed", False)
        s_pct  = alert_obj.confidence_score
        c_pct  = (s_pct + ml_pct) / 2 if ml_ok else s_pct
        dc     = "#3fb950" if alert_obj.direction == "BULLISH" else "#f85149"
        cc     = "#3fb950" if c_pct >= 65 else "#f0883e" if c_pct >= 45 else "#8b949e"

        eng_list  = getattr(alert_obj, "engines_triggered", []) or []
        eng_count = len(eng_list)
        eng_text  = f"{eng_count}/7"
        eng_color = "#3fb950" if eng_count >= 5 else "#f0883e" if eng_count >= 3 else "#8b949e"

        if is_confirmed:
            type_text, type_color, type_bg = "✅ CONFIRMED", "#ffd700", "#1a1a00"
        else:
            type_text, type_color, type_bg = "🎯 TRADE", "#f85149", "#2d1414"

        entry = getattr(alert_obj, "entry_reference",    0.0) or 0.0
        sl    = getattr(alert_obj, "stop_loss_reference", 0.0) or 0.0
        t1    = getattr(alert_obj, "target1", getattr(alert_obj, "target_reference", 0.0)) or 0.0
        t2    = getattr(alert_obj, "target2", 0.0) or 0.0
        t3    = getattr(alert_obj, "target3", 0.0) or 0.0
        instr = getattr(alert_obj, "suggested_instrument", "—") or "—"

        def _price(v):
            return f"{v:.0f}" if v else "—"

        self._table.setItem(r,  0, _item(alert_obj.timestamp.strftime("%H:%M:%S"), "#8b949e"))
        self._table.setItem(r,  1, _item(alert_obj.index_name, "#58a6ff", bold=True))
        self._table.setItem(r,  2, _item(type_text, type_color, bold=True, bg=type_bg))
        self._table.setItem(r,  3, _item(alert_obj.direction, dc, bold=True))
        self._table.setItem(r,  4, _item(f"{s_pct:.0f}%", "#c9d1d9"))
        self._table.setItem(r,  5, _item(
            f"{ml_pct:.0f}%" if ml_ok else "—",
            "#58a6ff" if ml_ok else "#484f58", bold=ml_ok,
        ))
        self._table.setItem(r,  6, _item(f"{c_pct:.0f}%", cc, bold=True))
        self._table.setItem(r,  7, _item(eng_text, eng_color, bold=True))
        self._table.setItem(r,  8, _item(instr, "#c9d1d9"))
        self._table.setItem(r,  9, _item(_price(entry), "#3fb950", bold=True))
        self._table.setItem(r, 10, _item(_price(sl),    "#f85149", bold=True))
        self._table.setItem(r, 11, _item(_price(t1),    "#f0883e", bold=True))
        self._table.setItem(r, 12, _item(_price(t2),    "#f0883e"))
        self._table.setItem(r, 13, _item(_price(t3),    "#f0883e"))
        self._table.setItem(r, 14, _item("OPEN", "#484f58"))

        self._table.setRowHeight(r, 36 if is_confirmed else 30)
        self._table.selectRow(0)
        self._detail.show_trade(alert_obj)

        if self._table.rowCount() > 200:
            self._table.removeRow(200)
            self._row_alerts.pop(200, None)

    def _load_history(self):
        """Load today's TRADE_SIGNAL + CONFIRMED_SIGNAL from DB on startup."""
        try:
            from database.models import Alert
            from sqlalchemy import func
            today = date.today()
            with self._db.get_session() as s:
                rows = (
                    s.query(Alert)
                    .filter(
                        func.date(Alert.timestamp) == today,
                        Alert.alert_type.in_(["TRADE_SIGNAL", "CONFIRMED_SIGNAL"]),
                    )
                    .order_by(Alert.timestamp.asc())
                    .all()
                )
            for row in rows:
                self._insert_db_row(row)
            self._update_stats()
        except Exception:
            pass

    def _insert_db_row(self, row):
        """Insert a DB Alert row (not a live alert_obj) into the table."""
        r = 0
        self._table.insertRow(r)
        self._row_alerts = {k + 1: v for k, v in self._row_alerts.items()}
        self._row_alerts[0] = None  # DB rows have no live alert_obj

        is_confirmed = row.alert_type == "CONFIRMED_SIGNAL"
        s_pct  = row.confidence_score or 0.0
        dc     = "#3fb950" if row.direction == "BULLISH" else "#f85149"

        if is_confirmed:
            type_text, type_color, type_bg = "✅ CONFIRMED", "#ffd700", "#1a1a00"
        else:
            type_text, type_color, type_bg = "🎯 TRADE", "#f85149", "#2d1414"

        eng_count = row.engines_count or 0
        eng_color = "#3fb950" if eng_count >= 5 else "#f0883e" if eng_count >= 3 else "#8b949e"

        entry = row.entry_reference or 0.0
        sl    = row.stop_loss_reference or 0.0
        tgt   = row.target_reference or 0.0

        def _price(v):
            return f"{v:.0f}" if v else "—"

        self._table.setItem(r,  0, _item(row.timestamp.strftime("%H:%M:%S"), "#8b949e"))
        self._table.setItem(r,  1, _item(row.index_name, "#58a6ff", bold=True))
        self._table.setItem(r,  2, _item(type_text, type_color, bold=True, bg=type_bg))
        self._table.setItem(r,  3, _item(row.direction, dc, bold=True))
        self._table.setItem(r,  4, _item(f"{s_pct:.0f}%", "#c9d1d9"))
        self._table.setItem(r,  5, _item("—", "#484f58"))
        self._table.setItem(r,  6, _item(f"{s_pct:.0f}%", "#8b949e"))
        self._table.setItem(r,  7, _item(f"{eng_count}/7", eng_color, bold=True))
        self._table.setItem(r,  8, _item(row.suggested_instrument or "—", "#c9d1d9"))
        self._table.setItem(r,  9, _item(_price(entry), "#3fb950", bold=True))
        self._table.setItem(r, 10, _item(_price(sl),    "#f85149", bold=True))
        self._table.setItem(r, 11, _item(_price(tgt),   "#f0883e", bold=True))
        self._table.setItem(r, 12, _item("—", "#484f58"))
        self._table.setItem(r, 13, _item("—", "#484f58"))
        self._table.setItem(r, 14, _item("—", "#30363d"))
        self._table.setRowHeight(r, 36 if is_confirmed else 30)

    def _on_select(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        r = self._table.currentRow()
        ao = self._row_alerts.get(r)
        self._detail.show_trade(ao)

    def _on_threshold_changed(self, value):
        self._ml_threshold = value
        if value == 0:
            self._threshold_lbl.setText("(all signals pass)")
        else:
            self._threshold_lbl.setText(f"(ML ≥ {value}% required)")
        self._update_stats()

    def _clear(self):
        self._table.setRowCount(0)
        self._row_alerts.clear()
        self._detail.show_trade(None)
        self._update_stats()

    def _update_stats(self):
        try:
            from database.models import Alert, TradeOutcome
            from sqlalchemy import func
            today = date.today()
            with self._db.get_session() as s:
                total = s.query(Alert).filter(
                    func.date(Alert.timestamp) == today,
                    Alert.alert_type.in_(["TRADE_SIGNAL", "CONFIRMED_SIGNAL"]),
                ).count()
                confirmed = s.query(Alert).filter(
                    func.date(Alert.timestamp) == today,
                    Alert.alert_type == "CONFIRMED_SIGNAL",
                ).count()
                # Filter to TRADE_SIGNAL only — CONFIRMED_SIGNAL rows track the
                # same underlying move and would double-count wins/losses.
                closed = s.query(TradeOutcome).filter(
                    func.date(TradeOutcome.created_at) == today,
                    TradeOutcome.status == "CLOSED",
                    TradeOutcome.alert_type == "TRADE_SIGNAL",
                ).all()
                wins    = sum(1 for o in closed if o.outcome == "WIN")
                win_rate = (wins / len(closed) * 100) if closed else 0.0

            self._s_total.setText(str(total))
            self._s_conf.setText(str(confirmed))
            self._s_winrate.setText(f"{win_rate:.0f}%" if closed else "—")

            # ML stats from live rows
            ml_scores = []
            filtered  = 0
            for ao in self._row_alerts.values():
                if ao is None:
                    continue
                ml = getattr(ao, "ml_prediction", None)
                if ml and ml.is_available:
                    ml_scores.append(ml.ml_confidence)
                    if ml.ml_confidence < self._ml_threshold:
                        filtered += 1

            avg_ml = sum(ml_scores) / len(ml_scores) if ml_scores else 0.0
            self._s_avg_ml.setText(f"{avg_ml:.0f}%" if ml_scores else "—")
            self._s_filtered.setText(str(filtered) if self._ml_threshold > 0 else "—")
        except Exception:
            pass

    @staticmethod
    def _outcome_badge(outcome):
        s = outcome.outcome or outcome.status or "OPEN"
        if s == "WIN":
            return "WIN ✓", "#3fb950"
        elif s == "LOSS":
            return "SL ✗", "#f85149"
        elif s == "EOD":
            return "EOD", "#8b949e"
        elif outcome.t3_hit:
            return "T3 ✓", "#3fb950"
        elif outcome.t2_hit:
            return "T2 ✓", "#58a6ff"
        elif outcome.t1_hit:
            return "T1 ✓", "#f0883e"
        return "OPEN", "#484f58"
