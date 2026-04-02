"""
ui/ml_testing_tab.py
ML SUPER TESTING MACHINE Tab — Run comprehensive ML diagnostics from UI.

Tests:
- Feature validation (all 111 features)
- Trigger effectiveness (win rates)
- Model training & evaluation
- Scenario testing (9 market conditions)
- Generate synthetic test data
- Manual options export
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QScrollArea, QProgressBar, QTextEdit, QTabWidget,
    QGroupBox, QSpinBox, QComboBox, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot
from PySide6.QtGui import QColor, QFont

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


def _lbl(text="", bold=False, size=11, color="#c9d1d9"):
    l = QLabel(text)
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color: {color};")
    return l


def _item(text, color="#c9d1d9", bold=False, center=True, bg=None):
    it = QTableWidgetItem(str(text))
    it.setForeground(QColor(color))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    if bg:
        it.setBackground(QColor(bg))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


class MLTestWorker(QThread):
    """Worker thread for long-running ML tests."""
    
    progress = Signal(str)           # Progress message
    test_complete = Signal(dict)     # Final results
    error_occurred = Signal(str)     # Error message
    
    def __init__(self, test_type: str, **kwargs):
        super().__init__()
        self.test_type = test_type
        self.kwargs = kwargs
        self._running = True
    
    def run(self):
        try:
            if self.test_type == "full_test":
                self._run_full_test()
            elif self.test_type == "generate_data":
                self._generate_test_data()
            elif self.test_type == "export_options":
                self._export_options()
            elif self.test_type == "validate_features":
                self._validate_features()
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}")
            logger.exception("ML test failed")
    
    def _run_full_test(self):
        """Run complete ML diagnostic suite."""
        try:
            from ml.ml_super_tester import MLSuperTester
            
            self.progress.emit("⏳ Initializing ML Super Tester...")
            tester = MLSuperTester()
            
            self.progress.emit("🔄 Loading data...")
            self.progress.emit("🔄 Validating features (111 total)...")
            self.progress.emit("🔄 Analyzing trigger effectiveness...")
            self.progress.emit("🔄 Training XGBoost model...")
            self.progress.emit("🔄 Testing 9 market scenarios...")
            
            result = tester.run_full_test()
            
            self.progress.emit("✅ ML diagnostic complete!")
            
            self.test_complete.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(f"Full test failed: {str(e)}")

    def _generate_test_data(self):
        """Generate synthetic test data for 6 scenarios."""
        try:
            from ml.ml_testing_framework import HistoricalDataGenerator
            from pathlib import Path
            
            self.progress.emit("⏳ Generating realistic historical data...")
            
            gen = HistoricalDataGenerator(days=60)
            output_dir = Path("test_data")
            output_dir.mkdir(exist_ok=True)
            
            scenarios = [
                ("trending_bullish", lambda: gen.generate_trending_candles('BULLISH')),
                ("trending_bearish", lambda: gen.generate_trending_candles('BEARISH')),
                ("consolidation", lambda: gen.generate_consolidation_candles()),
                ("reversal", lambda: gen.generate_reversal_candles()),
                ("gap_up", lambda: gen.generate_gap_candles(gap_direction=1.0)),
                ("volatile", lambda: gen.generate_volatile_candles(vol_mult=2.0)),
            ]
            
            for name, gen_func in scenarios:
                self.progress.emit(f"📊 Generating {name}...")
                df = gen_func()
                filepath = output_dir / f"test_data_{name}.csv"
                df.to_csv(filepath, index=False)
                self.progress.emit(f"✅ Saved: {filepath} ({len(df)} rows)")
            
            self.test_complete.emit({"status": "success", "files": len(scenarios)})
            
        except Exception as e:
            self.error_occurred.emit(f"Data generation failed: {str(e)}")

    def _export_options(self):
        """Manual export of daily options data."""
        try:
            from ml.options_feature_engine import export_daily_options_data
            
            self.progress.emit("⏳ Exporting options data...")
            result = export_daily_options_data()
            
            if "error" not in result:
                self.progress.emit(f"✅ Options export complete!")
                self.progress.emit(f"  - EOD prices: {result['total_eod_rows']} rows")
                self.progress.emit(f"  - Snapshots: {result['total_snapshot_rows']} rows")
                self.progress.emit(f"  - ML features: {result['total_ml_features_rows']} rows")
                self.test_complete.emit(result)
            else:
                self.error_occurred.emit(result.get("error", "Unknown error"))
            
        except Exception as e:
            self.error_occurred.emit(f"Export failed: {str(e)}")

    def _validate_features(self):
        """Load and validate all 111 features."""
        try:
            from ml.ml_super_tester import MLDataLoader, FeatureEngineValidator
            
            self.progress.emit("⏳ Loading real training data...")
            loader = MLDataLoader()
            df = loader.load_real_training_data(days=30)
            
            self.progress.emit(f"✅ Loaded {len(df)} rows")
            self.progress.emit("🔄 Validating 111 features...")
            
            validator = FeatureEngineValidator()
            report = validator.validate_all_features(df)
            
            overall = report.get('overall', {})
            self.progress.emit(f"✅ Feature validation complete!")
            self.progress.emit(f"  - Coverage: {overall.get('coverage_pct', 0):.1f}%")
            self.progress.emit(f"  - Complete rows: {overall.get('complete_rows_pct', 0):.1f}%")
            self.progress.emit(f"  - Max NaN: {overall.get('max_nan_pct', 0):.1f}%")
            
            self.test_complete.emit(report)
            
        except Exception as e:
            self.error_occurred.emit(f"Feature validation failed: {str(e)}")
    
    def stop(self):
        self._running = False
        self.wait()


class MLTestingTab(QWidget):
    """Main ML Testing tab with buttons and results display."""
    
    def __init__(self):
        super().__init__()
        self._worker = None
        self._last_report = None
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # ── Header ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("🧠  ML SUPER TESTING MACHINE", bold=True, size=13, color="#58a6ff"))
        hdr.addWidget(_lbl("Comprehensive ML diagnostics", color="#8b949e", size=10))
        hdr.addStretch()
        layout.addLayout(hdr)
        
        # ── Tab widget for different sections ──────────────────────
        tabs = QTabWidget()
        
        # Tab 1: Quick Commands
        tabs.addTab(self._build_commands_tab(), "⚡  QUICK START")
        
        # Tab 2: Test Results
        tabs.addTab(self._build_results_tab(), "📊  RESULTS")
        
        # Tab 3: Progress Log
        tabs.addTab(self._build_log_tab(), "📝  LOG")
        
        layout.addWidget(tabs)
    
    def _build_commands_tab(self) -> QWidget:
        """Build Quick Start commands tab."""
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(10)
        
        # ── Full Test Section ─────────────────────────────────────
        group1 = QGroupBox("FULL ML DIAGNOSTIC (15-30 min)")
        g1_ly = QVBoxLayout(group1)
        
        lbl1 = _lbl("Run comprehensive test suite:", color="#8b949e", size=10)
        lbl1.setWordWrap(True)
        g1_ly.addWidget(lbl1)
        
        features1 = _lbl(
            "✓ Load real & synthetic data  ✓ Validate 111 features\n"
            "✓ Analyze 9 trigger win rates  ✓ Train XGBoost model\n"
            "✓ Test 9 market scenarios  ✓ Auto-generate JSON report",
            color="#a8ff78", size=9
        )
        features1.setWordWrap(True)
        g1_ly.addWidget(features1)
        
        self._btn_full_test = QPushButton("▶  RUN FULL TEST")
        self._btn_full_test.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none; "
            "padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background: #388bfd; }"
            "QPushButton:pressed { background: #1f6feb; }"
        )
        self._btn_full_test.clicked.connect(self.run_full_test)
        g1_ly.addWidget(self._btn_full_test)
        
        ly.addWidget(group1)
        
        # ── Data Generation Section ───────────────────────────────
        group2 = QGroupBox("GENERATE SYNTHETIC DATA (2-5 min)")
        g2_ly = QVBoxLayout(group2)
        
        lbl2 = _lbl("Create realistic test data for 6 scenarios:", color="#8b949e", size=10)
        lbl2.setWordWrap(True)
        g2_ly.addWidget(lbl2)
        
        features2 = _lbl(
            "✓ Trending Bullish/Bearish  ✓ Consolidation\n"
            "✓ Reversals  ✓ Gap Patterns  ✓ Volatility (IV expansion)",
            color="#a8ff78", size=9
        )
        features2.setWordWrap(True)
        g2_ly.addWidget(features2)
        
        self._btn_gen_data = QPushButton("📊  GENERATE TEST DATA")
        self._btn_gen_data.setStyleSheet(
            "QPushButton { background: #238636; color: white; border: none; "
            "padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background: #2ea043; }"
        )
        self._btn_gen_data.clicked.connect(self.generate_test_data)
        g2_ly.addWidget(self._btn_gen_data)
        
        ly.addWidget(group2)
        
        # ── Options Export Section ────────────────────────────────
        group3 = QGroupBox("OPTIONS DATA MANAGEMENT")
        g3_ly = QVBoxLayout(group3)
        
        lbl3 = _lbl("Export daily options data for ML training:", color="#8b949e", size=10)
        lbl3.setWordWrap(True)
        g3_ly.addWidget(lbl3)
        
        features3 = _lbl(
            "✓ EOD prices (11K+ rows)  ✓ Snapshots (1.5K rows)\n"
            "✓ ML Features (pre-computed)  ✓ Summary metadata",
            color="#a8ff78", size=9
        )
        features3.setWordWrap(True)
        g3_ly.addWidget(features3)
        
        self._btn_export_opt = QPushButton("📤  EXPORT OPTIONS DATA")
        self._btn_export_opt.setStyleSheet(
            "QPushButton { background: #f0883e; color: white; border: none; "
            "padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background: #fb8500; }"
        )
        self._btn_export_opt.clicked.connect(self.export_options_data)
        g3_ly.addWidget(self._btn_export_opt)
        
        ly.addWidget(group3)
        
        # ── Feature Validation ────────────────────────────────────
        group4 = QGroupBox("VALIDATE FEATURES (2-5 min)")
        g4_ly = QVBoxLayout(group4)
        
        lbl4 = _lbl("Check all 111 features in real training data:", color="#8b949e", size=10)
        lbl4.setWordWrap(True)
        g4_ly.addWidget(lbl4)
        
        features4 = _lbl(
            "✓ Check feature presence  ✓ Detect NaN/missing values\n"
            "✓ Analyze value ranges  ✓ Data quality report",
            color="#a8ff78", size=9
        )
        features4.setWordWrap(True)
        g4_ly.addWidget(features4)
        
        self._btn_validate = QPushButton("✓  VALIDATE FEATURES")
        self._btn_validate.setStyleSheet(
            "QPushButton { background: #3fb950; color: white; border: none; "
            "padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background: #4ade80; }"
        )
        self._btn_validate.clicked.connect(self.validate_features)
        g4_ly.addWidget(self._btn_validate)
        
        ly.addWidget(group4)
        
        ly.addStretch()
        
        return w
    
    def _build_results_tab(self) -> QWidget:
        """Build Results display tab."""
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(8)
        
        # ── Results header ────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("TEST RESULTS", bold=True, color="#58a6ff"))
        hdr.addStretch()
        
        self._btn_open_report = QPushButton("📂  Open Last Report")
        self._btn_open_report.setStyleSheet(
            "QPushButton { background: #30363d; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 5px 12px; border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background: #21262d; }"
        )
        self._btn_open_report.clicked.connect(self.open_last_report)
        hdr.addWidget(self._btn_open_report)
        
        ly.addLayout(hdr)
        
        # ── Results table ─────────────────────────────────────────
        self._results_table = QTableWidget()
        self._results_table.setColumnCount(2)
        self._results_table.setHorizontalHeaderLabels(["METRIC", "VALUE"])
        self._results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._results_table.setMaximumHeight(400)
        
        ly.addWidget(self._results_table)
        
        ly.addStretch()
        
        return w
    
    def _build_log_tab(self) -> QWidget:
        """Build Progress log tab."""
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(8)
        
        # ── Progress bar ──────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet(
            "QProgressBar { background: #161b22; border: 1px solid #30363d; border-radius: 3px; }"
            "QProgressBar::chunk { background: #3fb950; border-radius: 2px; }"
        )
        self._progress_bar.setValue(0)
        ly.addWidget(self._progress_bar)
        
        # ── Log text ──────────────────────────────────────────────
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            "QTextEdit { background: #0d1117; color: #8b949e; border: 1px solid #30363d; "
            "font-family: monospace; font-size: 10px; padding: 8px; }"
        )
        ly.addWidget(self._log_text)
        
        return w
    
    @Slot()
    def run_full_test(self):
        """Run complete ML diagnostic."""
        if self._worker and self._worker.isRunning():
            self._log("⚠️  Test already running!")
            return
        
        self._log_text.clear()
        self._results_table.setRowCount(0)
        self._progress_bar.setValue(0)
        
        self._log("🚀 Starting ML Full Diagnostic...")
        self._disable_buttons()
        
        self._worker = MLTestWorker("full_test")
        self._worker.progress.connect(self._on_progress)
        self._worker.test_complete.connect(self._on_test_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
    
    @Slot()
    def generate_test_data(self):
        """Generate synthetic test data."""
        if self._worker and self._worker.isRunning():
            self._log("⚠️  Operation already running!")
            return
        
        self._log_text.clear()
        self._progress_bar.setValue(0)
        
        self._log("📊 Generating synthetic test data for 6 scenarios...")
        self._disable_buttons()
        
        self._worker = MLTestWorker("generate_data")
        self._worker.progress.connect(self._on_progress)
        self._worker.test_complete.connect(self._on_test_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
    
    @Slot()
    def export_options_data(self):
        """Export daily options data."""
        if self._worker and self._worker.isRunning():
            self._log("⚠️  Operation already running!")
            return
        
        self._log_text.clear()
        self._results_table.setRowCount(0)
        self._progress_bar.setValue(0)
        
        self._log("📤 Exporting options data...")
        self._disable_buttons()
        
        self._worker = MLTestWorker("export_options")
        self._worker.progress.connect(self._on_progress)
        self._worker.test_complete.connect(self._on_test_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
    
    @Slot()
    def validate_features(self):
        """Validate all 111 features."""
        if self._worker and self._worker.isRunning():
            self._log("⚠️  Operation already running!")
            return
        
        self._log_text.clear()
        self._results_table.setRowCount(0)
        self._progress_bar.setValue(0)
        
        self._log("✓ Validating all 111 features...")
        self._disable_buttons()
        
        self._worker = MLTestWorker("validate_features")
        self._worker.progress.connect(self._on_progress)
        self._worker.test_complete.connect(self._on_test_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
    
    @Slot(str)
    def _on_progress(self, msg: str):
        """Update progress log."""
        self._log(msg)
        self._progress_bar.setValue(
            min(self._progress_bar.value() + 5, 90)
        )
    
    @Slot(dict)
    def _on_test_complete(self, result: dict):
        """Test completed successfully."""
        self._progress_bar.setValue(100)
        self._last_report = result
        self._display_results(result)
        self._enable_buttons()
        
        self._log("✅ TEST COMPLETE")
    
    @Slot(str)
    def _on_error(self, error_msg: str):
        """Error occurred during test."""
        self._log(f"❌ {error_msg}")
        self._progress_bar.setValue(0)
        self._enable_buttons()
    
    def _log(self, msg: str):
        """Add message to log."""
        text = self._log_text.toPlainText()
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.setText(f"{text}\n[{timestamp}] {msg}")
        # Auto-scroll to bottom
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
    
    def _display_results(self, result: dict):
        """Display results in table."""
        self._results_table.setRowCount(0)
        
        if not result:
            return
        
        row = 0
        
        # Flatten nested dicts for display
        def add_row(key: str, value: Any, color: str = "#c9d1d9"):
            nonlocal row
            self._results_table.insertRow(row)
            
            # Format value
            if isinstance(value, float):
                val_str = f"{value:.2f}"
            elif isinstance(value, dict):
                val_str = json.dumps(value, indent=2)[:100]
            else:
                val_str = str(value)
            
            self._results_table.setItem(row, 0, _item(key, bold=True))
            self._results_table.setItem(row, 1, _item(val_str))
            row += 1
        
        # Display top-level results
        for key, value in result.items():
            if isinstance(value, (dict, list)):
                if key in ["trigger_win_rates", "scenario_results", "overall"]:
                    add_row(key, f"See JSON report")
                continue
            add_row(key, value)
    
    def _disable_buttons(self):
        """Disable all operation buttons."""
        self._btn_full_test.setEnabled(False)
        self._btn_gen_data.setEnabled(False)
        self._btn_export_opt.setEnabled(False)
        self._btn_validate.setEnabled(False)
    
    def _enable_buttons(self):
        """Enable all operation buttons."""
        self._btn_full_test.setEnabled(True)
        self._btn_gen_data.setEnabled(True)
        self._btn_export_opt.setEnabled(True)
        self._btn_validate.setEnabled(True)
    
    def open_last_report(self):
        """Open last generated report in file explorer."""
        try:
            from pathlib import Path
            import subprocess
            
            # Find latest report
            reports_dir = Path("logs")
            if not reports_dir.exists():
                self._log("❌ No reports directory found")
                return
            
            reports = list(reports_dir.glob("**/ml_test_report_*.json"))
            if not reports:
                self._log("❌ No reports found. Run a test first!")
                return
            
            latest = max(reports, key=lambda p: p.stat().st_mtime)
            self._log(f"📂 Opening: {latest}")
            
            # Open with default app
            if subprocess.os.name == 'nt':
                import os
                os.startfile(str(latest))
            else:
                subprocess.Popen(['xdg-open', str(latest)])
            
        except Exception as e:
            self._log(f"❌ Error: {str(e)}")
