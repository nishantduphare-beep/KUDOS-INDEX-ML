"""
ui/setup_tab.py
─────────────────────────────────────────────────────────────────
SETUPS tab — shows per-setup win rates, grades, and hit counts.
Auto-refreshes every 30 seconds from the setup_alerts DB table.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QPushButton
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from database.manager import get_db


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


_GRADE_COLOR = {
    "A++": "#ffd700",
    "A+":  "#3fb950",
    "A":   "#3fb950",
    "A-":  "#a8ff78",
    "B":   "#f0883e",
    "C-":  "#8b949e",
    "D":   "#484f58",
}

_GRADE_BG = {
    "A++": "#2a2000",
    "A+":  "#0d2010",
    "A":   "#0d2010",
    "A-":  "#0d1a0d",
    "B":   "#2d1c08",
    "C-":  "#1a1a1a",
    "D":   "#111111",
}

# Grade sort order (A++ first)
_GRADE_ORDER = {"A++": 0, "A+": 1, "A": 2, "A-": 3, "B": 4, "C-": 5, "D": 6}


class SetupTab(QWidget):
    """Tab showing per-setup performance statistics from the setup_alerts table."""

    COLUMNS = [
        "SETUP NAME", "GRADE", "EXP WR%", "ACT WR%",
        "TOTAL", "WINS", "T2 HITS", "T3 HITS", "AVG QUAL",
        "AVG P&L ₹", "TOTAL P&L ₹",
    ]

    def __init__(self):
        super().__init__()
        self._db = get_db()
        self._build_ui()

        # Auto-refresh every 30 s
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(30_000)
        self.refresh()

    # ─── UI build ────────────────────────────────────────────────

    def _build_ui(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("SETUP PERFORMANCE", "#58a6ff", bold=True, size=13))
        hdr.addWidget(_lbl("  Live win rates per setup — refreshes every 30 s", "#484f58", size=10))
        hdr.addStretch()

        self._lbl_total = _lbl("—", "#8b949e", size=10)
        hdr.addWidget(self._lbl_total)

        btn = QPushButton("⟳  Refresh")
        btn.setStyleSheet(
            "background:#21262d;color:#8b949e;border:1px solid #30363d;"
            "border-radius:4px;padding:4px 10px;"
        )
        btn.clicked.connect(self.refresh)
        hdr.addWidget(btn)
        ly.addLayout(hdr)

        # Main table
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#0d1117; color:#c9d1d9; "
            "gridline-color:#21262d; border:1px solid #30363d; }"
            "QHeaderView::section { background:#161b22; color:#8b949e; "
            "border:none; padding:5px; font-size:10px; font-weight:bold; }"
        )
        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(self.COLUMNS)):
            hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        ly.addWidget(self._table)

        # Summary bar
        sf = QFrame()
        sf.setStyleSheet(
            "background:#161b22; border:1px solid #30363d; border-radius:3px;"
        )
        sb = QHBoxLayout(sf)
        sb.setContentsMargins(12, 6, 12, 6)
        self._sum_total  = self._stat(sb, "TOTAL SETUPS")
        self._sum_fire   = self._stat(sb, "LABELED")
        self._sum_a_wr   = self._stat(sb, "A++ WR")
        self._sum_best   = self._stat(sb, "BEST SETUP")
        self._sum_pnl    = self._stat(sb, "TOTAL P&L ₹")
        sb.addStretch()
        ly.addWidget(sf)

        # Info line
        ly.addWidget(_lbl(
            "  Grades: A++=83%+  A+=67%+  A=56%+  A-=45%+  B=35%+  C-/D=low",
            "#484f58", size=9
        ))

    def _stat(self, parent, label):
        f = QFrame()
        l = QVBoxLayout(f)
        l.setContentsMargins(8, 0, 16, 0); l.setSpacing(1)
        l.addWidget(_lbl(label, "#8b949e", size=9))
        v = _lbl("—", "#e6edf3", bold=True, size=13)
        l.addWidget(v)
        parent.addWidget(f)
        return v

    # ─── Public ──────────────────────────────────────────────────

    def refresh(self):
        """Reload setup stats from DB and repopulate the table."""
        try:
            stats = self._db.get_setup_alert_stats()
            self._populate(stats)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"SetupTab refresh error: {e}")

    # ─── Internal ────────────────────────────────────────────────

    def _populate(self, stats):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        # Sort by grade order, then expected_wr desc within same grade
        stats_sorted = sorted(
            stats,
            key=lambda x: (_GRADE_ORDER.get(x["setup_grade"], 9), -x["expected_wr"])
        )

        total_labeled = 0
        best_wr = 0.0
        best_name = "—"
        axx_wr_total = 0
        axx_count = 0
        grand_total_pnl = 0.0

        for row_data in stats_sorted:
            r = self._table.rowCount()
            self._table.insertRow(r)

            grade  = row_data["setup_grade"]
            gc     = _GRADE_COLOR.get(grade, "#8b949e")
            bg     = _GRADE_BG.get(grade, "#0d1117")
            exp_wr = row_data["expected_wr"]
            act_wr = row_data["actual_wr"]
            total  = row_data["total"]
            wins   = row_data["wins"]
            t2     = row_data["t2_count"]
            t3     = row_data["t3_count"]
            avg_q  = row_data["avg_quality"]

            # Actual WR color: green if ≥ expected, amber if close, red if far below
            wr_diff = act_wr - exp_wr
            wr_color = (
                "#3fb950" if wr_diff >= -5
                else "#f0883e" if wr_diff >= -15
                else "#f85149"
            )
            # Only color meaningfully if we have enough samples
            if total < 5:
                wr_color = "#484f58"

            avg_pnl   = row_data.get("avg_pnl", 0.0)
            total_pnl = row_data.get("total_pnl", 0.0)
            pnl_color = "#3fb950" if avg_pnl > 0 else "#f85149" if avg_pnl < 0 else "#484f58"
            tot_color = "#3fb950" if total_pnl > 0 else "#f85149" if total_pnl < 0 else "#484f58"

            self._table.setItem(r, 0, _item(row_data["setup_name"], "#c9d1d9", center=False, bg=bg))
            self._table.setItem(r, 1, _item(grade, gc, bold=True, bg=bg))
            self._table.setItem(r, 2, _item(f"{exp_wr:.0f}%", "#8b949e", bg=bg))
            self._table.setItem(r, 3, _item(
                f"{act_wr:.1f}%" if total >= 5 else f"({act_wr:.0f}%)",
                wr_color, bold=(total >= 5), bg=bg
            ))
            self._table.setItem(r, 4, _item(str(total), "#c9d1d9", bg=bg))
            self._table.setItem(r, 5, _item(str(wins), "#3fb950" if wins > 0 else "#484f58", bg=bg))
            self._table.setItem(r, 6, _item(str(t2), "#a8ff78" if t2 > 0 else "#484f58", bg=bg))
            self._table.setItem(r, 7, _item(str(t3), "#ffd700" if t3 > 0 else "#484f58", bg=bg))
            self._table.setItem(r, 8, _item(f"{avg_q:.2f}", "#8b949e", bg=bg))
            self._table.setItem(r, 9, _item(
                f"₹{avg_pnl:+,.0f}" if avg_pnl != 0 else "—",
                pnl_color, bold=(total >= 5 and avg_pnl != 0), bg=bg
            ))
            self._table.setItem(r, 10, _item(
                f"₹{total_pnl:+,.0f}" if total_pnl != 0 else "—",
                tot_color, bold=(total_pnl != 0), bg=bg
            ))

            self._table.setRowHeight(r, 32)

            total_labeled += total
            grand_total_pnl += row_data.get("total_pnl", 0.0)
            if total >= 5 and act_wr > best_wr:
                best_wr = act_wr
                best_name = row_data["setup_name"]
            if grade == "A++" and total >= 3:
                axx_wr_total += act_wr
                axx_count += 1

        self._table.setSortingEnabled(True)

        # Update summary bar
        self._sum_total.setText(str(len(stats_sorted)))
        self._sum_fire.setText(str(total_labeled))

        if axx_count > 0:
            avg_axx = axx_wr_total / axx_count
            c = "#3fb950" if avg_axx >= 70 else "#f0883e"
            self._sum_a_wr.setText(f"{avg_axx:.1f}%")
            self._sum_a_wr.setStyleSheet(f"color:{c};font-size:13px;font-weight:bold;")
        else:
            self._sum_a_wr.setText("—")

        self._sum_best.setText(best_name[:20] if best_name != "—" else "—")
        if best_name != "—":
            self._sum_best.setStyleSheet("color:#ffd700;font-size:11px;font-weight:bold;")

        pnl_c = "#3fb950" if grand_total_pnl > 0 else "#f85149" if grand_total_pnl < 0 else "#8b949e"
        self._sum_pnl.setText(f"₹{grand_total_pnl:+,.0f}" if grand_total_pnl != 0 else "—")
        self._sum_pnl.setStyleSheet(f"color:{pnl_c};font-size:13px;font-weight:bold;")

        self._lbl_total.setText(f"{total_labeled} labeled alerts  |  {len(stats_sorted)} setups")
