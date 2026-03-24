"""
ui/ledger_tab.py
─────────────────────────────────────────────────────────────────
Trade Ledger — two sub-tabs: Paper and Live.

Columns:
  Symbol | Qty | Entry | SL | Booked | Cap Used | Cap Released | P&L

Top bar:
  Total P&L with duration selector (Today / This Week / This Month / All Time)

Data sources:
  Paper  — OrderManager._today_orders (mode=PAPER); in-memory this session
  Live   — TradeOutcome DB rows (status=CLOSED) joined with Alert for position size
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QTabWidget, QSizePolicy, QPushButton
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QBrush

import config

logger = logging.getLogger(__name__)

_COLS = ["SYMBOL", "QTY", "ENTRY", "SL", "BOOKED", "CAP USED", "CAP RELEASED", "P&L"]
_DURATIONS = ["Today", "This Week", "This Month", "All Time"]


def _lbl(text="", bold=False, size=12, color="#c9d1d9", align=Qt.AlignLeft):
    lbl = QLabel(text)
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {color};")
    lbl.setAlignment(align)
    return lbl


def _since(duration: str) -> datetime:
    now = datetime.now()
    if duration == "Today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if duration == "This Week":
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    if duration == "This Month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return datetime(2020, 1, 1)   # All Time


def _table_style():
    return """
        QTableWidget {
            background: #0d1117; color: #c9d1d9;
            font-size: 11px; border: none; gridline-color: #21262d;
        }
        QHeaderView::section {
            background: #161b22; color: #8b949e; font-size: 10px;
            font-weight: bold; border: none;
            border-bottom: 1px solid #30363d; padding: 4px 8px;
        }
        QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #21262d; }
    """


class LedgerTable(QTableWidget):
    """Reusable ledger table with standard columns and colour rules."""

    def __init__(self, parent=None):
        super().__init__(0, len(_COLS), parent)
        self.setHorizontalHeaderLabels(_COLS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setStyleSheet(_table_style())
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)    # SYMBOL stretches
        for c in range(1, len(_COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.setSortingEnabled(True)

    def _item(self, text: str, color: str = "#c9d1d9",
               bold: bool = False, align=Qt.AlignCenter) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QBrush(QColor(color)))
        item.setTextAlignment(align)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        return item

    def populate(self, rows: List[dict]):
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            pnl       = rec.get("pnl", 0.0) or 0.0
            pnl_color = "#3fb950" if pnl > 0 else "#f85149" if pnl < 0 else "#8b949e"
            outcome   = rec.get("outcome", "")
            out_color = "#3fb950" if outcome == "WIN" else "#f85149" if outcome == "LOSS" else "#8b949e"
            sign      = "+" if pnl > 0 else ""

            cells = [
                # (text, color, bold, align)
                (rec.get("symbol", "—"),           "#c9d1d9", False, Qt.AlignLeft),
                (str(rec.get("qty", "—")),          "#e6edf3", False, Qt.AlignCenter),
                (_fmt(rec.get("entry")),             "#58a6ff", False, Qt.AlignCenter),
                (_fmt(rec.get("sl")),                "#f85149", False, Qt.AlignCenter),
                (_fmt(rec.get("booked")),            out_color, True,  Qt.AlignCenter),
                (_fmt_inr(rec.get("cap_used")),      "#8b949e", False, Qt.AlignRight),
                (_fmt_inr(rec.get("cap_released")),  "#8b949e", False, Qt.AlignRight),
                (f"{sign}₹{abs(pnl):,.0f}",          pnl_color, True,  Qt.AlignRight),
            ]
            for c, (text, color, bold, align) in enumerate(cells):
                self.setItem(r, c, self._item(text, color, bold, align))
            self.setRowHeight(r, 28)
        self.setSortingEnabled(True)


def _fmt(val) -> str:
    if val is None or val == 0:
        return "—"
    return f"{float(val):.1f}"


def _fmt_inr(val) -> str:
    if val is None or val == 0:
        return "—"
    return f"₹{float(val):,.0f}"


class LedgerTab(QWidget):
    """
    Trade ledger with Paper and Live sub-tabs.
    Duration filter at the top controls which rows are shown.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._order_manager  = None
        self._db             = None
        self._duration       = "Today"
        self._build_ui()

        # Auto-refresh every 30 s when tab is visible
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(30_000)

    def set_order_manager(self, om):
        self._order_manager = om

    def set_db(self, db):
        self._db = db

    # ─── UI construction ─────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Summary bar ──────────────────────────────────────────
        summary = QFrame()
        summary.setObjectName("LedgerSummary")
        summary.setStyleSheet("""
            #LedgerSummary {
                background: #161b22; border: 1px solid #30363d; border-radius: 4px;
            }
        """)
        s_layout = QHBoxLayout(summary)
        s_layout.setContentsMargins(16, 10, 16, 10)
        s_layout.setSpacing(24)

        # Paper P&L
        s_layout.addWidget(_lbl("PAPER P&L", bold=False, size=10, color="#8b949e"))
        self._paper_pnl_lbl = _lbl("₹0", bold=True, size=14, color="#f0883e")
        s_layout.addWidget(self._paper_pnl_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #30363d;")
        s_layout.addWidget(sep)

        # Live P&L
        s_layout.addWidget(_lbl("LIVE P&L", bold=False, size=10, color="#8b949e"))
        self._live_pnl_lbl = _lbl("₹0", bold=True, size=14, color="#3fb950")
        s_layout.addWidget(self._live_pnl_lbl)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #30363d;")
        s_layout.addWidget(sep2)

        # Combined
        s_layout.addWidget(_lbl("COMBINED", bold=False, size=10, color="#8b949e"))
        self._combined_pnl_lbl = _lbl("₹0", bold=True, size=16, color="#e6edf3")
        s_layout.addWidget(self._combined_pnl_lbl)

        s_layout.addStretch()

        # Duration selector
        s_layout.addWidget(_lbl("DURATION", bold=False, size=10, color="#8b949e"))
        self._duration_cb = QComboBox()
        self._duration_cb.addItems(_DURATIONS)
        self._duration_cb.setFixedHeight(26)
        self._duration_cb.setStyleSheet("""
            QComboBox {
                background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
                padding: 3px 8px; border-radius: 3px; font-size: 11px;
                min-width: 110px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #161b22; color: #c9d1d9;
                selection-background-color: #1f6feb;
                border: 1px solid #30363d;
            }
        """)
        self._duration_cb.currentTextChanged.connect(self._on_duration_changed)
        s_layout.addWidget(self._duration_cb)

        # Refresh button
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(26, 26)
        refresh_btn.setStyleSheet("""
            QPushButton { background: #21262d; color: #8b949e; border: 1px solid #30363d;
                border-radius: 3px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #30363d; color: #c9d1d9; }
        """)
        refresh_btn.clicked.connect(self.refresh)
        s_layout.addWidget(refresh_btn)
        layout.addWidget(summary)

        # ── Sub-tabs ─────────────────────────────────────────────
        self._sub_tabs = QTabWidget()
        self._sub_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #30363d; background: #0d1117; }
            QTabBar::tab {
                background: #161b22; color: #8b949e;
                padding: 6px 20px; border: 1px solid #30363d; border-bottom: none;
                font-size: 11px; font-weight: bold;
            }
            QTabBar::tab:selected { background: #0d1117; color: #f0883e;
                border-top: 2px solid #f0883e; }
            QTabBar::tab:hover { background: #21262d; color: #c9d1d9; }
        """)

        # Paper sub-tab
        paper_widget = QWidget()
        paper_layout = QVBoxLayout(paper_widget)
        paper_layout.setContentsMargins(0, 8, 0, 0)
        paper_layout.setSpacing(4)
        self._paper_count_lbl = _lbl("0 trades", size=10, color="#484f58")
        paper_layout.addWidget(self._paper_count_lbl)
        self._paper_table = LedgerTable()
        paper_layout.addWidget(self._paper_table)

        # Live sub-tab
        live_widget = QWidget()
        live_layout = QVBoxLayout(live_widget)
        live_layout.setContentsMargins(0, 8, 0, 0)
        live_layout.setSpacing(4)
        self._live_count_lbl = _lbl("0 trades", size=10, color="#484f58")
        live_layout.addWidget(self._live_count_lbl)
        self._live_table = LedgerTable()
        live_layout.addWidget(self._live_table)

        self._sub_tabs.addTab(paper_widget, "📋  PAPER TRADES")
        self._sub_tabs.addTab(live_widget,  "⚡  LIVE TRADES")
        layout.addWidget(self._sub_tabs)

    # ─── Data loading ─────────────────────────────────────────────

    def _on_duration_changed(self, text: str):
        self._duration = text
        self.refresh()

    def refresh(self):
        since = _since(self._duration)
        paper_rows = self._load_paper_rows(since)
        live_rows  = self._load_live_rows(since)

        self._paper_table.populate(paper_rows)
        self._live_table.populate(live_rows)

        paper_pnl = sum(r.get("pnl", 0.0) or 0.0 for r in paper_rows)
        live_pnl  = sum(r.get("pnl", 0.0) or 0.0 for r in live_rows)
        combined  = paper_pnl + live_pnl

        self._paper_count_lbl.setText(
            f"{len(paper_rows)} trade{'s' if len(paper_rows) != 1 else ''}"
        )
        self._live_count_lbl.setText(
            f"{len(live_rows)} trade{'s' if len(live_rows) != 1 else ''}"
        )

        def _pnl_str(v): return f"{'+' if v > 0 else ''}₹{v:,.0f}"
        def _pnl_color(v): return "#3fb950" if v > 0 else "#f85149" if v < 0 else "#484f58"

        self._paper_pnl_lbl.setText(_pnl_str(paper_pnl))
        self._paper_pnl_lbl.setStyleSheet(
            f"color: {_pnl_color(paper_pnl)}; font-weight: bold; font-size: 14px;")

        self._live_pnl_lbl.setText(_pnl_str(live_pnl))
        self._live_pnl_lbl.setStyleSheet(
            f"color: {_pnl_color(live_pnl)}; font-weight: bold; font-size: 14px;")

        self._combined_pnl_lbl.setText(_pnl_str(combined))
        self._combined_pnl_lbl.setStyleSheet(
            f"color: {_pnl_color(combined)}; font-weight: bold; font-size: 16px;")

    def _load_paper_rows(self, since: datetime) -> List[dict]:
        """Load paper trades from OrderManager (current session)."""
        if self._order_manager is None:
            return []
        rows = []
        try:
            with self._order_manager._lock:
                all_today = list(self._order_manager._today_orders)
            for rec in all_today:
                if rec.get("mode") != "PAPER":
                    continue
                placed = rec.get("placed_at")
                if placed and placed < since:
                    continue
                qty        = rec.get("qty", 0) or 0
                entry      = rec.get("entry", 0.0) or 0.0
                sl         = rec.get("sl", 0.0) or 0.0
                tp         = rec.get("tp", 0.0) or 0.0
                pnl        = rec.get("pnl", 0.0) or 0.0
                status     = rec.get("status", "")
                # Booked = the price at which the trade exited
                if "T3" in status:
                    booked = tp
                elif "T2" in status:
                    booked = tp * 0.7 + entry * 0.3   # approx T2
                elif "T1" in status:
                    booked = tp * 0.5 + entry * 0.5   # approx T1
                elif "SL" in status:
                    booked = sl
                else:
                    booked = entry  # still open / EOD
                cap_used     = entry * qty
                cap_released = booked * qty if booked else 0.0
                outcome = ("WIN"  if pnl > 0 else
                           "LOSS" if pnl < 0 else "OPEN")
                rows.append({
                    "symbol":       rec.get("symbol", "—"),
                    "qty":          qty,
                    "entry":        entry,
                    "sl":           sl,
                    "booked":       booked if booked != entry else None,
                    "cap_used":     cap_used,
                    "cap_released": cap_released if cap_released != cap_used else None,
                    "pnl":          pnl,
                    "outcome":      outcome,
                })
        except Exception as e:
            logger.error(f"LedgerTab _load_paper_rows: {e}")
        return rows

    def _load_live_rows(self, since: datetime) -> List[dict]:
        """Load CLOSED TradeOutcome rows from DB within the date range."""
        if self._db is None:
            return []
        rows = []
        try:
            with self._db.get_session() as session:
                from database.models import TradeOutcome, Alert
                from sqlalchemy import and_
                outcomes = (
                    session.query(TradeOutcome, Alert)
                    .join(Alert, TradeOutcome.alert_id == Alert.id, isouter=True)
                    .filter(
                        and_(
                            TradeOutcome.status == "CLOSED",
                            TradeOutcome.entry_time >= since,
                        )
                    )
                    .order_by(TradeOutcome.entry_time.desc())
                    .all()
                )
                for outcome, alert in outcomes:
                    rows.append(self._outcome_to_row(outcome, alert))
        except Exception as e:
            logger.error(f"LedgerTab _load_live_rows: {e}")
        return rows

    @staticmethod
    def _outcome_to_row(outcome, alert) -> dict:
        """Convert a TradeOutcome + Alert pair into a ledger row dict."""
        # ── Position sizing ───────────────────────────────────────
        lot_size     = config.SYMBOL_MAP.get(outcome.index_name or "", {}).get("lot_size", 1)
        rec_lots     = 1
        if alert and alert.raw_features:
            try:
                pos = (alert.raw_features if isinstance(alert.raw_features, dict)
                       else json.loads(alert.raw_features or "{}"))
                rec_lots = int(pos.get("_position", {}).get("recommended_lots", 1) or 1)
            except Exception:
                pass
        qty = lot_size * rec_lots

        # ── Prices ────────────────────────────────────────────────
        entry  = outcome.entry_price    or 0.0
        sl     = outcome.stop_loss_opt  or 0.0
        t1     = outcome.t1_opt         or 0.0
        t2     = outcome.t2_opt         or 0.0
        t3     = outcome.t3_opt         or 0.0

        # Booked = actual exit price if tracked, else best-fit from hit flags
        if outcome.exit_price and outcome.exit_price > 0:
            booked = outcome.exit_price
        elif outcome.t3_hit and t3:
            booked = t3
        elif outcome.t2_hit and t2:
            booked = t2
        elif outcome.t1_hit and t1:
            booked = t1
        elif outcome.sl_hit and sl:
            booked = sl
        else:
            booked = entry   # EOD flat — no clear exit

        # ── P&L ───────────────────────────────────────────────────
        pnl = (booked - entry) * qty if entry > 0 else 0.0

        cap_used     = entry  * qty
        cap_released = booked * qty

        # Symbol
        symbol = outcome.instrument or (
            alert.suggested_instrument if alert else "—"
        ) or "—"

        return {
            "symbol":       symbol,
            "qty":          qty,
            "entry":        entry,
            "sl":           sl,
            "booked":       booked if booked != entry else None,
            "cap_used":     cap_used,
            "cap_released": cap_released if cap_released != cap_used else None,
            "pnl":          round(pnl, 2),
            "outcome":      outcome.outcome or ("WIN" if pnl > 0 else "LOSS" if pnl < 0 else "—"),
        }
