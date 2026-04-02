"""
ui/deployment_control_panel.py
ML Deployment Control — Toggle auto-trading with safety checks + readiness indicator.

Shows:
- Auto-trading toggle
- Live trading toggle  
- ML Readiness indicator (0-100%)
- Last training date
- Current model metrics
"""

import json
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QFont

import config


def _lbl(text="", bold=False, size=11, color="#c9d1d9"):
    l = QLabel(text)
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color: {color};")
    return l


class MLReadinessIndicator(QFrame):
    """Shows ML model readiness (0-100%) with detailed metrics."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: #161b22; border: 1px solid #30363d; "
            "border-radius: 6px; padding: 12px; }"
        )
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_metrics)
        self._refresh_timer.start(5000)  # Refresh every 5 seconds
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # ── Header ────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("🧠 ML READINESS", bold=True, size=12, color="#58a6ff"))
        hdr.addStretch()
        
        self._readiness_lbl = _lbl("—%", bold=True, size=16, color="#3fb950")
        hdr.addWidget(self._readiness_lbl)
        layout.addLayout(hdr)
        
        # ── Readiness Bar ─────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 3px;
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f85149, stop:50 #f0883e, stop:100 #3fb950);
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._progress_bar)
        
        # ── Metrics Grid ──────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(12)
        
        # Row 1: Model metrics
        grid.addWidget(_lbl("Model F1:", color="#8b949e", size=10), 0, 0)
        self._f1_lbl = _lbl("—", color="#c9d1d9", size=10)
        grid.addWidget(self._f1_lbl, 0, 1)
        
        grid.addWidget(_lbl("Features:", color="#8b949e", size=10), 0, 2)
        self._features_lbl = _lbl("—", color="#c9d1d9", size=10)
        grid.addWidget(self._features_lbl, 0, 3)
        
        # Row 2: Paper trading metrics
        grid.addWidget(_lbl("Paper WR:", color="#8b949e", size=10), 1, 0)
        self._wr_lbl = _lbl("—", color="#c9d1d9", size=10)
        grid.addWidget(self._wr_lbl, 1, 1)
        
        grid.addWidget(_lbl("Scenarios:", color="#8b949e", size=10), 1, 2)
        self._scenarios_lbl = _lbl("—", color="#c9d1d9", size=10)
        grid.addWidget(self._scenarios_lbl, 1, 3)
        
        # Row 3: Training info
        grid.addWidget(_lbl("Last Train:", color="#8b949e", size=10), 2, 0)
        self._train_date_lbl = _lbl("Never", color="#f0883e", size=10)
        grid.addWidget(self._train_date_lbl, 2, 1)
        
        grid.addWidget(_lbl("Status:", color="#8b949e", size=10), 2, 2)
        self._status_lbl = _lbl("❌ NOT READY", color="#f85149", size=10, bold=True)
        grid.addWidget(self._status_lbl, 2, 3)
        
        layout.addLayout(grid)
        
        # ── Status message ────────────────────────────
        self._status_msg = _lbl(
            "Train model via ML TESTER → RUN FULL TEST",
            color="#8b949e", size=9
        )
        self._status_msg.setWordWrap(True)
        layout.addWidget(self._status_msg)
    
    @Slot()
    def refresh_metrics(self):
        """Load and display ML metrics."""
        try:
            # Find latest report
            reports_dir = Path("logs")
            if not reports_dir.exists():
                self._set_not_ready("No logs directory")
                return
            
            reports = list(reports_dir.glob("**/ml_test_report_*.json"))
            if not reports:
                self._set_not_ready("No training report")
                return
            
            latest_report = max(reports, key=lambda p: p.stat().st_mtime)
            
            with open(latest_report, 'r') as f:
                report = json.load(f)
            
            # Extract metrics
            test_f1 = report.get('tests', {}).get('model_metrics', {}).get('test', {}).get('f1', 0)
            feature_coverage = report.get('tests', {}).get('feature_validation', {}).get('overall', {}).get('coverage_pct', 0)
            scenario_count = len([s for s in report.get('tests', {}).get('scenario_results', {}).values() if s.get('stats', {}).get('win_rate', 0) > 50])
            
            # Calculate readiness (0-100%)
            readiness = int(
                (test_f1 * 40) +           # F1 score: 40%
                (min(feature_coverage, 100) * 30) +  # Features: 30%
                (scenario_count * 3.33)    # Scenarios (max 9): 30%
            )
            readiness = min(max(readiness, 0), 100)
            
            # Update UI
            self._progress_bar.setValue(readiness)
            self._readiness_lbl.setText(f"{readiness}%")
            
            self._f1_lbl.setText(f"{test_f1:.2f}")
            self._features_lbl.setText(f"{feature_coverage:.0f}%")
            self._scenarios_lbl.setText(f"{scenario_count}/9")
            
            train_date = report.get('timestamp', 'Unknown')
            if train_date != 'Unknown':
                try:
                    dt = datetime.fromisoformat(train_date)
                    train_date = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            self._train_date_lbl.setText(train_date)
            
            # Determine status
            if readiness >= 70 and test_f1 >= 0.65:
                self._status_lbl.setText("✅ READY")
                self._status_lbl.setStyleSheet("color: #3fb950; font-weight: bold;")
                self._status_msg.setText("Model is ready! You can enable auto-trading.")
                self._status_msg.setStyleSheet("color: #3fb950;")
            elif readiness >= 50:
                self._status_lbl.setText("⚠️  RISKY")
                self._status_lbl.setStyleSheet("color: #f0883e; font-weight: bold;")
                self._status_msg.setText("Model needs more training or data.")
                self._status_msg.setStyleSheet("color: #f0883e;")
            else:
                self._set_not_ready(f"Readiness: {readiness}%")
            
        except Exception as e:
            self._set_not_ready(f"Error: {str(e)}")
    
    def _set_not_ready(self, reason: str):
        self._progress_bar.setValue(0)
        self._readiness_lbl.setText("0%")
        self._f1_lbl.setText("—")
        self._features_lbl.setText("—")
        self._scenarios_lbl.setText("—")
        self._train_date_lbl.setText("Never")
        self._status_lbl.setText("❌ NOT READY")
        self._status_lbl.setStyleSheet("color: #f85149; font-weight: bold;")
        self._status_msg.setText(reason)
        self._status_msg.setStyleSheet("color: #8b949e;")


class DeploymentControlPanel(QWidget):
    """Main deployment control widget with toggles and readiness."""
    
    config_changed = Signal(str, bool)   # (setting_name, enabled)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # ── ML Readiness Indicator ────────────────────
        self._readiness = MLReadinessIndicator()
        layout.addWidget(self._readiness)
        
        # ── Separator ─────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)
        
        # ── Control Toggles ───────────────────────────
        controls_lbl = _lbl("DEPLOYMENT CONTROLS", bold=True, size=12, color="#58a6ff")
        layout.addWidget(controls_lbl)
        
        # Auto-trade toggle
        auto_layout = QHBoxLayout()
        auto_layout.addWidget(_lbl("🤖 Auto-Trading:", color="#c9d1d9", size=11))
        
        self._auto_trade_btn = QPushButton("OFF")
        self._auto_trade_btn.setCheckable(True)
        self._auto_trade_btn.setChecked(config.AUTO_TRADE_ENABLED)
        self._auto_trade_btn.setMaximumWidth(80)
        self._auto_trade_btn.setStyleSheet(
            "QPushButton { background: #484f58; color: #c9d1d9; border: 1px solid #484f58; "
            "padding: 6px 12px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:checked { background: #238636; border-color: #238636; }"
        )
        self._auto_trade_btn.clicked.connect(self._on_auto_trade_toggled)
        self._auto_trade_btn.setText("ON" if config.AUTO_TRADE_ENABLED else "OFF")
        auto_layout.addWidget(self._auto_trade_btn)
        
        auto_layout.addWidget(_lbl(
            "Automatically execute high-confidence trades",
            color="#8b949e", size=9
        ))
        auto_layout.addStretch()
        layout.addLayout(auto_layout)
        
        # Paper trading toggle
        paper_layout = QHBoxLayout()
        paper_layout.addWidget(_lbl("📄 Paper Mode:", color="#c9d1d9", size=11))
        
        self._paper_btn = QPushButton("ON")
        self._paper_btn.setCheckable(True)
        self._paper_btn.setChecked(config.AUTO_TRADE_PAPER_MODE)
        self._paper_btn.setMaximumWidth(80)
        self._paper_btn.setStyleSheet(
            "QPushButton { background: #238636; color: #c9d1d9; border: 1px solid #238636; "
            "padding: 6px 12px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:checked { background: #238636; border-color: #238636; }"
            "QPushButton:!checked { background: #f85149; border-color: #f85149; }"
        )
        self._paper_btn.clicked.connect(self._on_paper_toggled)
        paper_layout.addWidget(self._paper_btn)
        
        paper_layout.addWidget(_lbl(
            "Simulate trades (GREEN=Paper, RED=Live Money)",
            color="#8b949e", size=9
        ))
        paper_layout.addStretch()
        layout.addLayout(paper_layout)
        
        # Live trading toggle (with warning)
        live_layout = QHBoxLayout()
        live_layout.addWidget(_lbl("💰 LIVE TRADING:", color="#c9d1d9", size=11, bold=True))
        
        self._live_btn = QPushButton("OFF")
        self._live_btn.setCheckable(True)
        self._live_btn.setChecked(config.LIVE_TRADING_MODE)
        self._live_btn.setMaximumWidth(80)
        self._live_btn.setStyleSheet(
            "QPushButton { background: #484f58; color: #c9d1d9; border: 1px solid #484f58; "
            "padding: 6px 12px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:checked { background: #f85149; border-color: #f85149; color: white; }"
        )
        self._live_btn.clicked.connect(self._on_live_toggled)
        self._live_btn.setText("ON" if config.LIVE_TRADING_MODE else "OFF")
        live_layout.addWidget(self._live_btn)
        
        live_layout.addWidget(_lbl(
            "⚠️ REAL MONEY - Only enable after full paper testing!",
            color="#f85149", size=9
        ))
        live_layout.addStretch()
        layout.addLayout(live_layout)
        
        # ── Safety Info ───────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #30363d;")
        layout.addWidget(sep2)
        
        safety_lbl = _lbl("SAFETY LIMITS (Active)", bold=True, size=11, color="#f0883e")
        layout.addWidget(safety_lbl)
        
        limits_grid = QGridLayout()
        limits_grid.setSpacing(8)
        
        limits_grid.addWidget(_lbl("Max Daily Loss:", color="#8b949e", size=10), 0, 0)
        limits_grid.addWidget(_lbl(f"₹{config.AUTO_TRADE_MAX_DAILY_LOSS:,}", color="#c9d1d9", size=10), 0, 1)
        
        limits_grid.addWidget(_lbl("Max Daily Trades:", color="#8b949e", size=10), 0, 2)
        limits_grid.addWidget(_lbl(f"{config.AUTO_TRADE_MAX_DAILY_ORDERS}", color="#c9d1d9", size=10), 0, 3)
        
        limits_grid.addWidget(_lbl("Min Confidence:", color="#8b949e", size=10), 1, 0)
        limits_grid.addWidget(_lbl(f"{config.AUTO_TRADE_MIN_CONFIDENCE}%", color="#c9d1d9", size=10), 1, 1)
        
        limits_grid.addWidget(_lbl("Min Triggers:", color="#8b949e", size=10), 1, 2)
        limits_grid.addWidget(_lbl(f"{config.AUTO_TRADE_MIN_ENGINES}/9", color="#c9d1d9", size=10), 1, 3)
        
        layout.addLayout(limits_grid)
        
        # ── Trading Hours ─────────────────────────────
        hours_lbl = _lbl("TRADING HOURS (IST)", bold=True, size=11, color="#58a6ff")
        layout.addWidget(hours_lbl)
        
        hours_grid = QGridLayout()
        hours_grid.setSpacing(8)
        
        hours_grid.addWidget(_lbl("Start:", color="#8b949e", size=10), 0, 0)
        hours_grid.addWidget(_lbl(config.LIVE_TRADING_START_TIME, color="#3fb950", size=10, bold=True), 0, 1)
        
        hours_grid.addWidget(_lbl("End:", color="#8b949e", size=10), 0, 2)
        hours_grid.addWidget(_lbl(config.LIVE_TRADING_STOP_TIME, color="#f0883e", size=10, bold=True), 0, 3)
        
        hours_grid.addWidget(_lbl("Force Close:", color="#8b949e", size=10), 1, 0)
        hours_grid.addWidget(_lbl(config.LIVE_TRADING_STOP_LOSS_TIME, color="#f85149", size=10, bold=True), 1, 1)
        
        layout.addLayout(hours_grid)
        
        layout.addStretch()
    
    @Slot()
    def _on_auto_trade_toggled(self):
        """Toggle auto-trading."""
        enabled = self._auto_trade_btn.isChecked()
        self._auto_trade_btn.setText("ON" if enabled else "OFF")
        self.config_changed.emit("AUTO_TRADE_ENABLED", enabled)
        
        # Update config (runtime - not persisted)
        config.AUTO_TRADE_ENABLED = enabled
    
    @Slot()
    def _on_paper_toggled(self):
        """Toggle paper mode."""
        paper = self._paper_btn.isChecked()
        self._paper_btn.setText("ON" if paper else "OFF")
        
        # Update button color
        if paper:
            self._paper_btn.setStyleSheet(
                "QPushButton { background: #238636; color: #c9d1d9; border: 1px solid #238636; "
                "padding: 6px 12px; border-radius: 3px; font-weight: bold; }"
            )
        else:
            self._paper_btn.setStyleSheet(
                "QPushButton { background: #f85149; color: #c9d1d9; border: 1px solid #f85149; "
                "padding: 6px 12px; border-radius: 3px; font-weight: bold; }"
            )
        
        self.config_changed.emit("AUTO_TRADE_PAPER_MODE", paper)
        config.AUTO_TRADE_PAPER_MODE = paper
    
    @Slot()
    def _on_live_toggled(self):
        """Toggle live trading (with confirmation)."""
        if self._live_btn.isChecked():
            from PySide6.QtWidgets import QMessageBox
            
            # Safety check
            if not config.AUTO_TRADE_ENABLED:
                QMessageBox.warning(
                    self, 
                    "Cannot Enable Live Trading",
                    "Auto-trading must be enabled first!"
                )
                self._live_btn.setChecked(False)
                return
            
            # Readiness check
            readiness = int(self._readiness._progress_bar.value())
            if readiness < 70:
                QMessageBox.warning(
                    self,
                    "ML Model Not Ready",
                    f"ML Readiness: {readiness}%\n\n"
                    f"Train model to ≥70% readiness first!\n\n"
                    f"Go to ML TESTER → RUN FULL TEST"
                )
                self._live_btn.setChecked(False)
                return
            
            # Final confirmation
            reply = QMessageBox.warning(
                self,
                "⚠️  ENABLE LIVE TRADING?",
                "This will trade with REAL MONEY!\n\n"
                "Ensure you have:\n"
                "✓ Tested in paper mode 1-2 weeks\n"
                "✓ Win rate > 60% consistently\n"
                "✓ Broker credentials configured\n\n"
                "Do you want to continue?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                self._live_btn.setChecked(False)
                return
        
        enabled = self._live_btn.isChecked()
        self._live_btn.setText("ON" if enabled else "OFF")
        
        self.config_changed.emit("LIVE_TRADING_MODE", enabled)
        config.LIVE_TRADING_MODE = enabled
    
    def refresh_readiness(self):
        """Manually refresh ML readiness."""
        self._readiness.refresh_metrics()
