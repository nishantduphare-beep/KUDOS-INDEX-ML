"""
ui/s11_tab.py
─────────────────────────────────────────────────────────────────
S11 Setup Tab — dedicated monitor for S11 paper trade system.

Layout:
  ┌──────────────────── STATS BAR ───────────────────────────────┐
  │ Total | Wins | Losses | Win% | T2 rate | T3 rate | P&L ₹     │
  └──────────────────────────────────────────────────────────────┘
  ┌──── EARLY ALERTS (today) ────────────────────────────────────┐
  │ Time | Index | Direction | Spot | Conf% | Engines            │
  └──────────────────────────────────────────────────────────────┘
  ┌──── OPEN POSITIONS ──────────────────────────────────────────┐
  │ Index | Dir | Entry | SL | T1 | T2 | T3 | Units | P&L@T2    │
  └──────────────────────────────────────────────────────────────┘
  ┌──── CLOSED TODAY ────────────────────────────────────────────┐
  │ Time | Index | Dir | Entry | Exit | Outcome | P&L ₹         │
  └──────────────────────────────────────────────────────────────┘
"""

from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont


# ─── Helpers ─────────────────────────────────────────────────────

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
    w = QLabel(str(text))
    w.setStyleSheet(
        f"color:{color}; font-size:{size}px;"
        + (" font-weight:bold;" if bold else "")
    )
    return w


def _section_label(title: str) -> QLabel:
    lbl = QLabel(f"  {title}")
    lbl.setStyleSheet(
        "color:#58a6ff; font-size:11px; font-weight:bold;"
        " background:#161b22; padding:4px 0;"
    )
    return lbl


def _dir_color(direction: str) -> str:
    if direction == "BULLISH":
        return "#3fb950"
    elif direction == "BEARISH":
        return "#f85149"
    return "#c9d1d9"


def _outcome_color(outcome: str) -> str:
    if outcome == "WIN":
        return "#3fb950"
    elif outcome == "LOSS":
        return "#f85149"
    return "#e3b341"  # NEUTRAL


def _make_table(headers: list, row_height: int = 26) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(False)
    t.setShowGrid(False)
    t.setStyleSheet("""
        QTableWidget {
            background:#0d1117; color:#c9d1d9;
            border:none; gridline-color:#21262d;
            font-size:11px;
        }
        QTableWidget::item { padding:2px 6px; border-bottom:1px solid #21262d; }
        QTableWidget::item:selected { background:#1f2d3d; }
        QHeaderView::section {
            background:#161b22; color:#8b949e;
            font-size:10px; font-weight:bold;
            border:none; border-bottom:1px solid #30363d;
            padding:4px 6px;
        }
    """)
    t.verticalHeader().setDefaultSectionSize(row_height)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    return t


# ─── Stats Bar ────────────────────────────────────────────────────

class _StatsBar(QFrame):
    """Horizontal stat strip: Total | Wins | Losses | Win% | T2% | T3% | P&L"""

    def __init__(self):
        super().__init__()
        self.setObjectName("S11StatsBar")
        self.setStyleSheet(
            "#S11StatsBar { background:#161b22;"
            " border:1px solid #30363d; border-radius:5px; }"
        )
        self.setFixedHeight(60)

        ly = QHBoxLayout(self)
        ly.setContentsMargins(16, 6, 16, 6)
        ly.setSpacing(0)

        self._cells = {}
        for key, label in [
            ("total",    "TOTAL"),
            ("wins",     "WINS"),
            ("losses",   "LOSSES"),
            ("win_rate", "WIN %"),
            ("t2_rate",  "T2 RATE"),
            ("t3_rate",  "T3 RATE"),
            ("total_pnl","TOTAL P&L"),
        ]:
            c = QFrame()
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            cl = QVBoxLayout(c)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            k = _lbl(label, "#8b949e", size=9)
            k.setAlignment(Qt.AlignCenter)
            v = _lbl("—", "#e6edf3", bold=True, size=13)
            v.setAlignment(Qt.AlignCenter)
            cl.addWidget(k)
            cl.addWidget(v)
            ly.addWidget(c)
            self._cells[key] = v

            # Divider
            div = QFrame()
            div.setFixedWidth(1)
            div.setStyleSheet("background:#30363d;")
            ly.addWidget(div)

    def refresh(self, stats: dict) -> None:
        pnl   = stats.get("total_pnl", 0)
        wins  = stats.get("wins", 0)
        color = "#3fb950" if pnl >= 0 else "#f85149"
        self._cells["total"   ].setText(str(stats.get("total",    0)))
        self._cells["wins"    ].setText(str(wins))
        self._cells["losses"  ].setText(str(stats.get("losses",   0)))
        self._cells["win_rate"].setText(f"{stats.get('win_rate', 0):.1f}%")
        self._cells["t2_rate" ].setText(f"{stats.get('t2_rate',  0):.1f}%")
        self._cells["t3_rate" ].setText(f"{stats.get('t3_rate',  0):.1f}%")
        self._cells["total_pnl"].setText(f"₹{pnl:+,.0f}")
        self._cells["total_pnl"].setStyleSheet(
            f"color:{color}; font-size:13px; font-weight:bold;"
        )


# ─── Main Tab ─────────────────────────────────────────────────────

class S11Tab(QWidget):
    """
    Tab widget for the S11 paper-trade monitor.

    Usage:
        tab = S11Tab()
        tab.set_monitor(s11_monitor_instance)   # called from main_window
        # refresh is called automatically via internal QTimer every 5 s
        # also call tab.refresh() from outside on new S11 alert
    """

    _EARLY_HEADERS = ["Time", "Index", "Direction", "Spot", "Conf%", "Engines"]
    _OPEN_HEADERS  = ["Index", "Dir", "Entry Spot", "Entry ₹", "SL (spot)",
                      "T1", "T2", "T3", "Units", "P&L@T2 ₹", "T1?", "T2?"]
    _CLOSED_HEADERS = ["Time", "Index", "Dir", "Entry ₹", "Exit ₹",
                       "Reason", "Outcome", "P&L ₹"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)   # refresh every 5 s

    def set_monitor(self, monitor) -> None:
        """Inject S11Monitor instance after tab creation."""
        self._monitor = monitor
        self.refresh()

    # ─── UI construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Stats bar
        self._stats_bar = _StatsBar()
        root.addWidget(self._stats_bar)

        # Early Alerts
        root.addWidget(_section_label("S11 EARLY ALERTS — today"))
        self._early_tbl = _make_table(self._EARLY_HEADERS, row_height=24)
        self._early_tbl.setMaximumHeight(130)
        self._early_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self._early_tbl)

        # Open Positions
        root.addWidget(_section_label("OPEN PAPER POSITIONS"))
        self._open_tbl = _make_table(self._OPEN_HEADERS, row_height=28)
        self._open_tbl.setMaximumHeight(180)
        root.addWidget(self._open_tbl)

        # Closed Today
        root.addWidget(_section_label("CLOSED TODAY"))
        self._closed_tbl = _make_table(self._CLOSED_HEADERS, row_height=26)
        root.addWidget(self._closed_tbl)

    # ─── Refresh ─────────────────────────────────────────────────

    def refresh(self) -> None:
        """Pull latest data from S11Monitor and repaint all tables."""
        if self._monitor is None:
            return
        try:
            self._refresh_stats()
            self._refresh_early()
            self._refresh_open()
            self._refresh_closed()
        except Exception:
            pass

    def _refresh_stats(self) -> None:
        stats = self._monitor.get_stats()
        self._stats_bar.refresh(stats)

    def _refresh_early(self) -> None:
        alerts = self._monitor.get_early_alerts_today()
        # Most recent first
        alerts = sorted(alerts, key=lambda a: a.get("timestamp", datetime.min), reverse=True)
        self._early_tbl.setRowCount(len(alerts))
        for r, a in enumerate(alerts):
            ts  = a.get("timestamp", "")
            ts_str = ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else str(ts)
            engines = a.get("engines", [])
            eng_str = ", ".join(engines[:3]) + ("…" if len(engines) > 3 else "")
            dc = _dir_color(a.get("direction", ""))
            self._early_tbl.setItem(r, 0, _item(ts_str))
            self._early_tbl.setItem(r, 1, _item(a.get("index_name", ""), bold=True))
            self._early_tbl.setItem(r, 2, _item(a.get("direction", ""),  color=dc, bold=True))
            self._early_tbl.setItem(r, 3, _item(f"{a.get('spot_price', 0):.0f}"))
            self._early_tbl.setItem(r, 4, _item(f"{a.get('confidence_score', 0):.1f}%"))
            self._early_tbl.setItem(r, 5, _item(eng_str, center=False))

    def _refresh_open(self) -> None:
        positions = self._monitor.get_open_positions()
        self._open_tbl.setRowCount(len(positions))
        for r, p in enumerate(positions):
            dc    = _dir_color(p.get("direction", ""))
            t1_hit = p.get("t1_hit", False)
            t2_hit = p.get("t2_hit", False)
            # Row highlight if T2 already trailed
            bg = "#1a2a1a" if t2_hit else ("#1a1a2a" if t1_hit else None)

            self._open_tbl.setItem(r, 0,  _item(p.get("index_name", ""), bold=True, bg=bg))
            self._open_tbl.setItem(r, 1,  _item(p.get("direction",  ""), color=dc,  bold=True, bg=bg))
            self._open_tbl.setItem(r, 2,  _item(f"{p.get('entry_spot',  0):.0f}", bg=bg))
            self._open_tbl.setItem(r, 3,  _item(f"{p.get('entry_price', 0):.2f}", bg=bg))
            self._open_tbl.setItem(r, 4,  _item(f"{p.get('spot_sl',  0):.0f}", color="#f85149", bg=bg))
            self._open_tbl.setItem(r, 5,  _item(f"{p.get('spot_t1', 0):.0f}", bg=bg))
            self._open_tbl.setItem(r, 6,  _item(f"{p.get('spot_t2', 0):.0f}", bg=bg))
            self._open_tbl.setItem(r, 7,  _item(f"{p.get('spot_t3', 0):.0f}", bg=bg))
            self._open_tbl.setItem(r, 8,  _item(str(p.get("units", 0)), bg=bg))
            pnl_t2 = p.get("pnl_at_t2", 0)
            self._open_tbl.setItem(r, 9,  _item(
                f"₹{pnl_t2:+,.0f}",
                color="#3fb950" if pnl_t2 >= 0 else "#f85149",
                bold=True, bg=bg,
            ))
            self._open_tbl.setItem(r, 10, _item("✓" if t1_hit else "·",
                                                 color="#3fb950" if t1_hit else "#8b949e", bg=bg))
            self._open_tbl.setItem(r, 11, _item("✓" if t2_hit else "·",
                                                 color="#3fb950" if t2_hit else "#8b949e", bg=bg))

    def _refresh_closed(self) -> None:
        closed = self._monitor.get_closed_today()
        closed = sorted(closed, key=lambda c: c.get("entry_time", datetime.min), reverse=True)
        self._closed_tbl.setRowCount(len(closed))
        for r, c in enumerate(closed):
            outcome = c.get("outcome", "")
            dc      = _dir_color(c.get("direction", ""))
            oc      = _outcome_color(outcome)
            pnl     = c.get("realized_pnl", 0)
            et = c.get("entry_time", "")
            et_str = et.strftime("%H:%M") if isinstance(et, datetime) else str(et)
            self._closed_tbl.setItem(r, 0, _item(et_str))
            self._closed_tbl.setItem(r, 1, _item(c.get("index_name",  ""), bold=True))
            self._closed_tbl.setItem(r, 2, _item(c.get("direction",   ""), color=dc, bold=True))
            self._closed_tbl.setItem(r, 3, _item(f"{c.get('entry_price', 0):.2f}"))
            self._closed_tbl.setItem(r, 4, _item(f"{c.get('exit_price',  0):.2f}"))
            self._closed_tbl.setItem(r, 5, _item(c.get("exit_reason", "")))
            self._closed_tbl.setItem(r, 6, _item(outcome, color=oc, bold=True))
            self._closed_tbl.setItem(r, 7, _item(
                f"₹{pnl:+,.0f}",
                color="#3fb950" if pnl >= 0 else "#f85149",
                bold=True,
            ))
