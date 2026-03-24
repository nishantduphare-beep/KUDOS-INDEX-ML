"""
ui/ml_report_widget.py
ML Report Panel — shows model analysis and config suggestions with Apply toggles.

Appears as a section in the Alerts tab (or any parent that hosts it).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QCheckBox, QGridLayout, QTextEdit,
    QProgressBar, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

import config


def _lbl(text="", bold=False, size=11, color="#c9d1d9"):
    l = QLabel(text)
    f = QFont(); f.setPointSize(size); f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color: {color};")
    return l


class MLReportWidget(QWidget):
    """
    Shows ML model analysis and actionable config suggestions.
    User can toggle each suggestion and click "Apply Selected".
    """

    config_applied = Signal(dict)   # emitted when user applies suggestions

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: dict = {}
        self._suggestion_checks: dict = {}   # key → QCheckBox
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── Header ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = _lbl("ML SIGNAL INTELLIGENCE REPORT", bold=True, size=12, color="#58a6ff")
        self._refresh_btn = QPushButton("Generate Report")
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: #238636; color: white; border: none; "
            "padding: 5px 14px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background: #2ea043; }"
        )
        self._refresh_btn.clicked.connect(self.generate_report)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._refresh_btn)
        layout.addLayout(hdr)

        # ── Status / summary text ─────────────────────────────────
        self._summary_lbl = QLabel("Click 'Generate Report' after labeling at least 30 signals.")
        self._summary_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._summary_lbl.setWordWrap(True)
        layout.addWidget(self._summary_lbl)

        # ── Scrollable report area ────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._report_inner = QWidget()
        self._report_layout = QVBoxLayout(self._report_inner)
        self._report_layout.setContentsMargins(0, 0, 0, 0)
        self._report_layout.setSpacing(10)
        scroll.setWidget(self._report_inner)
        layout.addWidget(scroll)

        # ── Apply button ──────────────────────────────────────────
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        self._apply_btn = QPushButton("Apply Selected Suggestions")
        self._apply_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none; "
            "padding: 6px 18px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background: #388bfd; }"
            "QPushButton:disabled { background: #21262d; color: #484f58; }"
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply_suggestions)
        apply_row.addWidget(self._apply_btn)
        layout.addLayout(apply_row)

    # ─── Report generation ────────────────────────────────────────

    def generate_report(self):
        try:
            from ml.model_manager import get_model_manager
            mm = get_model_manager()
            self._report = mm.generate_report()
        except Exception as e:
            self._summary_lbl.setText(f"Report error: {e}")
            return

        if "error" in self._report:
            self._summary_lbl.setText(self._report["error"])
            return

        self._summary_lbl.setText(self._report.get("summary_text", "Report generated."))
        self._build_report_panels()
        self._apply_btn.setEnabled(True)

    def _build_report_panels(self):
        # Clear existing content
        while self._report_layout.count():
            item = self._report_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._suggestion_checks.clear()

        r = self._report

        # ── 1. Threshold Analysis ─────────────────────────────────
        self._report_layout.addWidget(self._section_header("THRESHOLD ANALYSIS"))
        th_grid = QGridLayout()
        th_grid.addWidget(_lbl("THRESHOLD", bold=True, color="#8b949e"), 0, 0)
        th_grid.addWidget(_lbl("SIGNALS",   bold=True, color="#8b949e"), 0, 1)
        th_grid.addWidget(_lbl("PRECISION", bold=True, color="#8b949e"), 0, 2)
        th_grid.addWidget(_lbl("RECALL",    bold=True, color="#8b949e"), 0, 3)
        th_grid.addWidget(_lbl("F1",        bold=True, color="#8b949e"), 0, 4)

        recommended = r.get("recommended_threshold", 4)
        for row_i, (th, metrics) in enumerate(
            sorted(r.get("threshold_analysis", {}).items()), start=1
        ):
            is_rec = (th == recommended)
            clr = "#f0883e" if is_rec else "#c9d1d9"
            suffix = " ← RECOMMENDED" if is_rec else ""
            th_grid.addWidget(_lbl(f"{th}+ engines{suffix}", bold=is_rec, color=clr), row_i, 0)
            th_grid.addWidget(_lbl(str(metrics.get("signals", 0)),        color=clr), row_i, 1)
            th_grid.addWidget(_lbl(f"{metrics.get('precision',0):.0%}",   color=clr), row_i, 2)
            th_grid.addWidget(_lbl(f"{metrics.get('recall',0):.0%}",      color=clr), row_i, 3)
            th_grid.addWidget(_lbl(f"{metrics.get('f1',0):.2f}",          color=clr), row_i, 4)

        th_frame = QFrame()
        th_frame.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius:4px; padding:8px;")
        th_frame.setLayout(th_grid)
        self._report_layout.addWidget(th_frame)

        # ── 2. Engine Win Rates ───────────────────────────────────
        ew = r.get("engine_win_rates", {})
        if ew:
            self._report_layout.addWidget(self._section_header("ENGINE WIN RATES"))
            ew_grid = QGridLayout()
            ew_grid.addWidget(_lbl("ENGINE", bold=True, color="#8b949e"), 0, 0)
            ew_grid.addWidget(_lbl("WIN RATE", bold=True, color="#8b949e"), 0, 1)
            ew_grid.addWidget(_lbl("STRENGTH", bold=True, color="#8b949e"), 0, 2)
            for ri, (eng, rate) in enumerate(ew.items(), start=1):
                color = "#3fb950" if rate > 0.6 else "#f0883e" if rate > 0.4 else "#f85149"
                ew_grid.addWidget(_lbl(eng.upper(), color=color), ri, 0)
                ew_grid.addWidget(_lbl(f"{rate:.0%}", bold=True, color=color), ri, 1)
                bar = QProgressBar()
                bar.setMaximum(100); bar.setValue(int(rate * 100))
                bar.setFixedHeight(8); bar.setTextVisible(False)
                bar.setStyleSheet(f"QProgressBar{{background:#21262d;border:none;border-radius:4px}}"
                                  f"QProgressBar::chunk{{background:{color};border-radius:4px}}")
                ew_grid.addWidget(bar, ri, 2)
            ew_frame = QFrame()
            ew_frame.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius:4px; padding:8px;")
            ew_frame.setLayout(ew_grid)
            self._report_layout.addWidget(ew_frame)

        # ── 3. Top Features ───────────────────────────────────────
        fi = r.get("feature_importance", {})
        if fi:
            self._report_layout.addWidget(self._section_header("TOP 10 PREDICTIVE FEATURES"))
            fi_grid = QGridLayout()
            fi_grid.addWidget(_lbl("FEATURE", bold=True, color="#8b949e"), 0, 0)
            fi_grid.addWidget(_lbl("IMPORTANCE", bold=True, color="#8b949e"), 0, 1)
            for ri, (feat, imp) in enumerate(list(fi.items())[:10], start=1):
                color = "#58a6ff" if ri <= 3 else "#c9d1d9"
                fi_grid.addWidget(_lbl(feat, color=color), ri, 0)
                bar = QProgressBar()
                bar.setMaximum(1000); bar.setValue(int(imp * 1000))
                bar.setFixedHeight(8); bar.setTextVisible(False)
                bar.setStyleSheet("QProgressBar{background:#21262d;border:none;border-radius:4px}"
                                  "QProgressBar::chunk{background:#58a6ff;border-radius:4px}")
                fi_grid.addWidget(bar, ri, 1)
            fi_frame = QFrame()
            fi_frame.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius:4px; padding:8px;")
            fi_frame.setLayout(fi_grid)
            self._report_layout.addWidget(fi_frame)

        # ── 4. Context stats ──────────────────────────────────────
        idx_acc  = r.get("index_accuracy", {})
        hour_acc = r.get("hour_accuracy", {})
        if idx_acc or hour_acc:
            self._report_layout.addWidget(self._section_header("PERFORMANCE CONTEXT"))
            ctx_grid = QGridLayout()
            ri = 0
            if idx_acc:
                ctx_grid.addWidget(_lbl("Best index:", color="#8b949e"), ri, 0)
                best_idx = r.get("best_index", "NIFTY")
                ctx_grid.addWidget(_lbl(best_idx, bold=True, color="#3fb950"), ri, 1)
                ri += 1
            if r.get("best_time_window"):
                ctx_grid.addWidget(_lbl("Best time window:", color="#8b949e"), ri, 0)
                ctx_grid.addWidget(_lbl(r["best_time_window"], bold=True, color="#3fb950"), ri, 1)
            ctx_frame = QFrame()
            ctx_frame.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius:4px; padding:8px;")
            ctx_frame.setLayout(ctx_grid)
            self._report_layout.addWidget(ctx_frame)

        # ── 5. Suggested Config with toggles ─────────────────────
        suggested = r.get("suggested_config", {})
        if suggested:
            self._report_layout.addWidget(self._section_header("SUGGESTED CONFIG CHANGES"))
            sug_frame = QFrame()
            sug_frame.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius:4px; padding:8px;")
            sug_layout = QVBoxLayout(sug_frame)

            apply_items = {
                "MIN_ENGINES_FOR_ALERT": suggested.get("MIN_ENGINES_FOR_ALERT"),
            }
            current_vals = {
                "MIN_ENGINES_FOR_ALERT": config.MIN_ENGINES_FOR_ALERT,
            }

            for key, val in apply_items.items():
                if val is None:
                    continue
                cur = current_vals.get(key, "?")
                cb = QCheckBox(
                    f"{key}:  {cur}  →  {val}  "
                    f"({'no change' if cur == val else 'will change'})"
                )
                cb.setChecked(cur != val)
                cb.setStyleSheet("color: #c9d1d9; font-size: 11px;")
                sug_layout.addWidget(cb)
                self._suggestion_checks[key] = (cb, val)

            self._report_layout.addWidget(sug_frame)

        self._report_layout.addStretch()

    def _section_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #8b949e; font-size: 10px; letter-spacing: 1px;")
        return lbl

    # ─── Apply ────────────────────────────────────────────────────

    def _apply_suggestions(self):
        applied = {}
        for key, (cb, val) in self._suggestion_checks.items():
            if cb.isChecked():
                if key == "MIN_ENGINES_FOR_ALERT":
                    config.MIN_ENGINES_FOR_ALERT = val
                    config.MIN_ENGINES_FOR_SIGNAL = val
                applied[key] = val

        if applied:
            self._summary_lbl.setText(
                f"Applied: " + ", ".join(f"{k}={v}" for k, v in applied.items())
            )
            self.config_applied.emit(applied)
