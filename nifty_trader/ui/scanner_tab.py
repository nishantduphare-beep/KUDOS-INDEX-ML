"""
ui/scanner_tab.py
Tab 2 — Early Move Scanner
Shows engine-by-engine status for each index.
"""

from datetime import datetime, timezone, timedelta, time as _time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QGridLayout, QProgressBar, QSizePolicy,
    QComboBox, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

import config


def _colored_item(text, color="#c9d1d9", bold=False, center=False):
    item = QTableWidgetItem(str(text))
    item.setForeground(QColor(color))
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    if center:
        item.setTextAlignment(Qt.AlignCenter)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


class EngineStatusWidget(QFrame):
    """Visual status panel for one index's engine outputs."""

    ENGINES = [
        "compression", "di_momentum", "volume_pressure",
        "liquidity_trap", "gamma_levels", "vwap_pressure", "market_regime",
    ]
    ENGINE_LABELS = {
        "compression":    "E1 COMPRESSION",
        "di_momentum":    "E2 DI MOMENTUM",
        "volume_pressure":"E3 VOL PRESSURE",
        "liquidity_trap": "E4 LIQ TRAP",
        "gamma_levels":   "E5 GAMMA WALL",
        "vwap_pressure":  "E6 VWAP",
        "market_regime":  "E7 REGIME",
    }

    def __init__(self, index_name: str):
        super().__init__()
        self.index_name = index_name
        self.setObjectName("EngineStatus")
        self.setStyleSheet("""
            #EngineStatus {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        self._build_ui()
        self._last_results: dict = {}

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header
        hdr_layout = QHBoxLayout()
        name_lbl = QLabel(self.index_name)
        name_lbl.setStyleSheet("color: #58a6ff; font-size: 13px; font-weight: bold;")
        self._score_lbl = QLabel("0%")
        self._score_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        hdr_layout.addWidget(name_lbl)
        hdr_layout.addStretch()
        hdr_layout.addWidget(self._score_lbl)
        layout.addLayout(hdr_layout)

        # Overall progress bar
        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setStyleSheet("""
            QProgressBar { background: #30363d; border-radius: 2px; border: none; }
            QProgressBar::chunk { background: #58a6ff; border-radius: 2px; }
        """)
        layout.addWidget(self._progress)
        layout.addSpacing(4)

        # Engine rows
        self._engine_rows: dict = {}
        for eng in self.ENGINES:
            row = self._make_engine_row(eng)
            layout.addLayout(row["layout"])
            self._engine_rows[eng] = row

        layout.addSpacing(4)

        # Alert status
        self._alert_lbl = QLabel("○ MONITORING")
        self._alert_lbl.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: bold;")
        self._alert_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._alert_lbl)

        # Threshold fire display (shows ✓/✗ at 3/4/5/6)
        self._thresh_lbl = QLabel("")
        self._thresh_lbl.setStyleSheet("color: #8b949e; font-size: 10px;")
        self._thresh_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._thresh_lbl)

    def _make_engine_row(self, engine: str):
        layout = QHBoxLayout()
        layout.setSpacing(8)

        dot   = QLabel("○")
        dot.setFixedWidth(14)
        dot.setStyleSheet("color: #30363d; font-size: 14px;")

        label = QLabel(self.ENGINE_LABELS[engine])
        label.setStyleSheet("color: #8b949e; font-size: 11px;")
        label.setFixedWidth(140)

        dir_lbl = QLabel("--")
        dir_lbl.setStyleSheet("color: #8b949e; font-size: 10px;")
        dir_lbl.setFixedWidth(60)

        str_bar = QProgressBar()
        str_bar.setMaximum(100)
        str_bar.setValue(0)
        str_bar.setTextVisible(False)
        str_bar.setFixedHeight(6)
        str_bar.setFixedWidth(80)
        str_bar.setStyleSheet("""
            QProgressBar { background: #21262d; border-radius: 3px; border: none; }
            QProgressBar::chunk { background: #3fb950; border-radius: 3px; }
        """)

        layout.addWidget(dot)
        layout.addWidget(label)
        layout.addWidget(dir_lbl)
        layout.addWidget(str_bar)
        layout.addStretch()
        return {"layout": layout, "dot": dot, "label": label,
                "dir": dir_lbl, "bar": str_bar}

    def update_from_results(self, results: dict, confidence: float, direction: str, engines_count: int):
        """Update display from engine result dict."""
        self._score_lbl.setText(f"Score: {confidence:.0f}%")
        self._progress.setValue(int(confidence))

        # Color progress by confidence
        color = "#3fb950" if confidence >= 75 else "#f0883e" if confidence >= 50 else "#58a6ff"
        self._progress.setStyleSheet(f"""
            QProgressBar {{ background: #30363d; border-radius: 2px; border: none; }}
            QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}
        """)

        for eng, row in self._engine_rows.items():
            res = results.get(eng, {})
            triggered  = res.get("is_triggered", False)
            eng_dir    = res.get("direction", "NEUTRAL")
            strength   = int(res.get("strength", 0) * 100)

            if triggered:
                dot_color = "#3fb950" if eng_dir == "BULLISH" else "#f85149" if eng_dir == "BEARISH" else "#f0883e"
                row["dot"].setStyleSheet(f"color: {dot_color}; font-size: 14px;")
                row["label"].setStyleSheet(f"color: #c9d1d9; font-size: 11px;")
                dir_color = "#3fb950" if eng_dir == "BULLISH" else "#f85149" if eng_dir == "BEARISH" else "#f0883e"
                row["dir"].setText(eng_dir[:4])
                row["dir"].setStyleSheet(f"color: {dir_color}; font-size: 10px; font-weight: bold;")
                chunk_color = "#3fb950" if eng_dir == "BULLISH" else "#f85149"
                row["bar"].setValue(strength)
                row["bar"].setStyleSheet(f"""
                    QProgressBar {{ background: #21262d; border-radius: 3px; border: none; }}
                    QProgressBar::chunk {{ background: {chunk_color}; border-radius: 3px; }}
                """)
            else:
                row["dot"].setStyleSheet("color: #30363d; font-size: 14px;")
                row["label"].setStyleSheet("color: #8b949e; font-size: 11px;")
                row["dir"].setText("--")
                row["dir"].setStyleSheet("color: #8b949e; font-size: 10px;")
                row["bar"].setValue(0)

        threshold = config.MIN_ENGINES_FOR_ALERT
        if engines_count >= threshold:
            arrow = "▲" if direction == "BULLISH" else "▼"
            color = "#3fb950" if direction == "BULLISH" else "#f85149"
            self._alert_lbl.setText(f"⚡ EARLY ALERT — {arrow} {direction} ({engines_count}/7)")
            self._alert_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
        else:
            self._alert_lbl.setText(f"○ MONITORING ({engines_count}/7 engines)")
            self._alert_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")

        # Multi-threshold fire indicator
        parts = []
        for th in (3, 4, 5, 6):
            if engines_count >= th:
                parts.append(f"<span style='color:#3fb950'>{th}+✓</span>")
            else:
                parts.append(f"<span style='color:#484f58'>{th}+✗</span>")
        self._thresh_lbl.setText("  ".join(parts))
        self._thresh_lbl.setTextFormat(Qt.RichText)


class ScannerTab(QWidget):

    def __init__(self, data_manager, signal_aggregator):
        super().__init__()
        self._dm = data_manager
        self._sa = signal_aggregator
        self._status_widgets: dict = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Title + sensitivity control + session status
        top = QHBoxLayout()
        title = QLabel("EARLY MOVE SCANNER — ENGINE STATUS")
        title.setStyleSheet("color: #58a6ff; font-size: 14px; font-weight: bold;")
        top.addWidget(title)
        top.addStretch()

        top.addWidget(QLabel("SENSITIVITY:"))
        self._sensitivity_combo = QComboBox()
        self._sensitivity_combo.setStyleSheet(
            "QComboBox { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 3px 8px; border-radius: 3px; }"
        )
        for label in config.SENSITIVITY_LEVELS:
            self._sensitivity_combo.addItem(label)
        # Set current: load from user_settings.json if available, else match config
        import json, os
        _settings_path = os.path.join(os.path.dirname(__file__), "..", "user_settings.json")
        _saved_label = None
        try:
            if os.path.exists(_settings_path):
                with open(_settings_path) as _f:
                    _saved_label = json.load(_f).get("sensitivity")
        except Exception:
            pass
        _labels = list(config.SENSITIVITY_LEVELS.keys())
        if _saved_label and _saved_label in _labels:
            self._sensitivity_combo.setCurrentIndex(_labels.index(_saved_label))
            _v = config.SENSITIVITY_LEVELS[_saved_label]
            config.MIN_ENGINES_FOR_ALERT = _v
            config.MIN_ENGINES_FOR_SIGNAL = _v + 1
        else:
            current_th = config.MIN_ENGINES_FOR_ALERT
            for i, (lbl, val) in enumerate(config.SENSITIVITY_LEVELS.items()):
                if val == current_th:
                    self._sensitivity_combo.setCurrentIndex(i)
                    break
        self._sensitivity_combo.currentTextChanged.connect(self._on_sensitivity_changed)
        top.addWidget(self._sensitivity_combo)
        top.addSpacing(16)

        self._session_lbl = QLabel("● MARKET CLOSED")
        self._session_lbl.setStyleSheet("color: #f85149; font-size: 11px; font-weight: bold;")
        top.addWidget(self._session_lbl)

        layout.addLayout(top)

        # Three engine status panels
        panels = QHBoxLayout()
        panels.setSpacing(12)
        for idx in config.INDICES:
            w = EngineStatusWidget(idx)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._status_widgets[idx] = w
            panels.addWidget(w)
        layout.addLayout(panels)

        # Scanner log table
        log_label = QLabel("SCANNER LOG")
        log_label.setStyleSheet("color: #8b949e; font-size: 11px; letter-spacing: 1px;")
        layout.addWidget(log_label)

        self._log_table = QTableWidget()
        self._log_table.setColumnCount(8)
        self._log_table.setHorizontalHeaderLabels([
            "TIME", "INDEX", "TYPE", "DIRECTION", "ENGINES", "CONFIDENCE",
            "ATR", "PCR"
        ])
        self._log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._log_table.setMaximumHeight(200)
        layout.addWidget(self._log_table)
        layout.addStretch()

    def _on_sensitivity_changed(self, label: str):
        val = config.SENSITIVITY_LEVELS.get(label, 4)
        config.MIN_ENGINES_FOR_ALERT = val
        config.MIN_ENGINES_FOR_SIGNAL = val + 1  # trade signal always requires 1 more engine
        # M1 fix: persist to user_settings.json so restart remembers the choice
        import json, os
        _settings_path = os.path.join(os.path.dirname(__file__), "..", "user_settings.json")
        try:
            _s = {}
            if os.path.exists(_settings_path):
                with open(_settings_path) as _f:
                    _s = json.load(_f)
            _s["sensitivity"] = label
            with open(_settings_path, "w") as _f:
                json.dump(_s, _f, indent=2)
        except Exception:
            pass

    def _update_session_status(self):
        """Update market session label using exchange hours (09:15–15:30), not signal window."""
        from datetime import time as _time, datetime
        now_ist = datetime.now(config.IST).time()
        exchange_open = _time(9, 15) <= now_ist <= _time(15, 30)
        if config.BROKER == "mock":
            self._session_lbl.setText("● MOCK (ALWAYS ON)")
            self._session_lbl.setStyleSheet("color: #f0883e; font-size: 11px; font-weight: bold;")
        elif exchange_open:
            self._session_lbl.setText("● MARKET OPEN")
            self._session_lbl.setStyleSheet("color: #3fb950; font-size: 11px; font-weight: bold;")
        else:
            self._session_lbl.setText("● MARKET CLOSED")
            self._session_lbl.setStyleSheet("color: #f85149; font-size: 11px; font-weight: bold;")

    def refresh(self):
        self._update_session_status()
        for idx in config.INDICES:
            df    = self._dm.get_df(idx)
            chain = self._dm.get_option_chain(idx)
            spot  = self._dm.get_spot(idx)
            if df is None:
                continue

            # Run all 7 triggering engines
            from engines.compression import CompressionDetector
            from engines.di_momentum import DIMomentumDetector
            from engines.option_chain import OptionChainDetector
            from engines.volume_pressure import VolumePressureDetector
            from engines.liquidity_trap import LiquidityTrapDetector
            from engines.gamma_levels import GammaLevelsDetector
            from engines.iv_expansion import IVExpansionDetector
            from engines.market_regime import MarketRegimeDetector

            comp_r   = CompressionDetector().evaluate(df)
            di_r     = DIMomentumDetector().evaluate(df)
            oc_r     = OptionChainDetector().evaluate(chain)
            vol_r    = VolumePressureDetector().evaluate(df)
            liq_r    = LiquidityTrapDetector().evaluate(df)
            gamma_r  = GammaLevelsDetector().evaluate(chain)
            iv_r     = IVExpansionDetector().evaluate(chain)
            regime_r = MarketRegimeDetector().evaluate(df)

            results = {
                "compression":    vars(comp_r),
                "di_momentum":    vars(di_r),
                "option_chain":   vars(oc_r),
                "volume_pressure":vars(vol_r),
                "liquidity_trap": vars(liq_r),
                "gamma_levels":   vars(gamma_r),
                "iv_expansion":   vars(iv_r),
                "market_regime":  vars(regime_r),
            }

            all_results = [comp_r, di_r, oc_r, vol_r, liq_r, gamma_r, iv_r, regime_r]
            triggered = sum(1 for r in all_results if r.is_triggered)
            votes     = {"BULLISH": 0, "BEARISH": 0}
            total_score = 0
            for r in all_results:
                total_score += r.score
                if r.direction in votes:
                    votes[r.direction] += 1
            direction = "BULLISH" if votes["BULLISH"] >= votes["BEARISH"] else "BEARISH"
            max_score = sum(config.CONFIDENCE_WEIGHTS.values())
            confidence = round((total_score / max_score) * 100, 1)

            self._status_widgets[idx].update_from_results(
                results, confidence, direction, triggered
            )

    def add_log_row(self, idx, alert_type, direction, engines_count, confidence, pcr, atr=0.0):
        self._log_table.insertRow(0)
        now = datetime.now().strftime("%H:%M:%S")
        dir_color = "#3fb950" if direction == "BULLISH" else "#f85149"

        if alert_type == "TRADE_SIGNAL":
            type_text  = "🎯 TRADE"
            type_color = "#f0883e"
        else:
            type_text  = "⚡ EARLY"
            type_color = "#58a6ff"

        self._log_table.setItem(0, 0, _colored_item(now, "#8b949e", center=True))
        self._log_table.setItem(0, 1, _colored_item(idx, "#58a6ff", bold=True, center=True))
        self._log_table.setItem(0, 2, _colored_item(type_text, type_color, bold=True, center=True))
        self._log_table.setItem(0, 3, _colored_item(direction, dir_color, bold=True, center=True))
        self._log_table.setItem(0, 4, _colored_item(f"{engines_count}/7", "#f0883e", center=True))
        self._log_table.setItem(0, 5, _colored_item(f"{confidence:.1f}%", "#c9d1d9", center=True))
        self._log_table.setItem(0, 6, _colored_item(f"{atr:.1f}", "#c9d1d9", center=True))
        self._log_table.setItem(0, 7, _colored_item(f"{pcr:.3f}", "#c9d1d9", center=True))

        if self._log_table.rowCount() > 100:
            self._log_table.removeRow(100)
