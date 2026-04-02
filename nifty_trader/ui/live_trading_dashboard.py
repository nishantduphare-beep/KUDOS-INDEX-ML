"""
Live Trading Dashboard — Real-time monitoring tab for paper and live trading.

Displays:
  • Open positions
  • Real-time P&L
  • Daily statistics (win rate, avg win/loss)
  • Circuit breaker status
  • Emergency exit button (big red)
"""

import logging
from datetime import datetime
from typing import Optional

try:
    import config
except ImportError:
    import nifty_trader.config as config

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, 
    QTableWidgetItem, QProgressBar, QTextEdit, QMessageBox, QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger(__name__)


class LiveTradingDashboard(QWidget):
    """Real-time monitoring dashboard for live/paper trading"""
    
    emergency_exit_clicked = Signal()
    
    def __init__(self, order_manager, db):
        super().__init__()
        self.order_manager = order_manager
        self.db = db
        
        self.setWindowTitle("🟢 LIVE TRADING DASHBOARD")
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ecf0f1;
            }
            QLabel {
                color: #ecf0f1;
            }
            QPushButton {
                background-color: #34495e;
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c3e50;
            }
        """)
        
        self._setup_ui()
        
        # Refresh timer (every 2 seconds)
        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh)
        self.timer.start(2000)
    
    def _setup_ui(self):
        """Build dashboard layout"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # ─────────────────────────────────────────────────────────────────
        # TITLE BAR
        # ─────────────────────────────────────────────────────────────────
        title = QLabel("🔴 LIVE TRADING DASHBOARD")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #e74c3c;")
        layout.addWidget(title)
        
        # ─────────────────────────────────────────────────────────────────
        # KEY METRICS ROW (Open Trades, Daily P&L, Win Rate)
        # ─────────────────────────────────────────────────────────────────
        metrics_layout = QHBoxLayout()
        
        # Open Trades
        self.open_trades_box = self._create_metric_box("📊 Open Trades", "0")
        metrics_layout.addWidget(self.open_trades_box)
        
        # Daily P&L
        self.pnl_box = self._create_metric_box("💰 Daily P&L", "₹0")
        metrics_layout.addWidget(self.pnl_box)
        
        # Win Rate
        self.win_rate_box = self._create_metric_box("📈 Win Rate", "0%")
        metrics_layout.addWidget(self.win_rate_box)
        
        # Max Daily Loss
        self.daily_loss_box = self._create_metric_box("⚠️  Daily Loss", "₹0/₹0")
        metrics_layout.addWidget(self.daily_loss_box)
        
        layout.addLayout(metrics_layout)
        
        # ─────────────────────────────────────────────────────────────────
        # P&L PROGRESS BAR
        # ─────────────────────────────────────────────────────────────────
        pnl_label = QLabel("Daily P&L Progress:")
        pnl_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(pnl_label)
        
        self.pnl_bar = QProgressBar()
        self.pnl_bar.setRange(-10000, 10000)
        self.pnl_bar.setValue(0)
        self.pnl_bar.setMaximumHeight(30)
        layout.addWidget(self.pnl_bar)
        
        # ─────────────────────────────────────────────────────────────────
        # OPEN POSITIONS LIST
        # ─────────────────────────────────────────────────────────────────
        positions_label = QLabel("📋 Open Positions:")
        positions_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(positions_label)
        
        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(7)
        self.positions_table.setHorizontalHeaderLabels([
            "Symbol", "Qty", "Entry", "Current", "PnL", "Direction", "Time"
        ])
        self.positions_table.setMaximumHeight(150)
        layout.addWidget(self.positions_table)
        
        # ─────────────────────────────────────────────────────────────────
        # LIVE ORDERS LOG
        # ─────────────────────────────────────────────────────────────────
        orders_label = QLabel("📝 Recent Orders:")
        orders_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(orders_label)
        
        self.orders_log = QTextEdit()
        self.orders_log.setReadOnly(True)
        self.orders_log.setMaximumHeight(100)
        self.orders_log.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #2ecc71;
                font-family: Courier;
                font-size: 9pt;
            }
        """)
        layout.addWidget(self.orders_log)
        
        # ─────────────────────────────────────────────────────────────────
        # EMERGENCY EXIT BUTTON (BIG RED)
        # ─────────────────────────────────────────────────────────────────
        emergency_button = QPushButton("🚨 EMERGENCY EXIT - CLOSE ALL POSITIONS")
        emergency_button.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-size: 14pt;
                font-weight: bold;
                padding: 15px;
                border: 2px solid #a93226;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #a93226;
            }
            QPushButton:pressed {
                background-color: #922b21;
            }
        """)
        emergency_button.setMinimumHeight(60)
        emergency_button.clicked.connect(self._emergency_exit)
        layout.addWidget(emergency_button)
        
        # ─────────────────────────────────────────────────────────────────
        # STATUS BAR
        # ─────────────────────────────────────────────────────────────────
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("color: #2ecc71; font-style: italic;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
    
    def _create_metric_box(self, label: str, value: str = "0") -> QWidget:
        """Create a metric display box"""
        box = QWidget()
        box_layout = QVBoxLayout()
        box_layout.setSpacing(5)
        
        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-weight: bold; font-size: 10pt; color: #95a5a6;")
        box_layout.addWidget(label_widget)
        
        value_widget = QLabel(value)
        value_font = QFont()
        value_font.setPointSize(14)
        value_font.setBold(True)
        value_widget.setFont(value_font)
        value_widget.setStyleSheet("color: #2ecc71; background-color: #34495e; padding: 8px; border-radius: 3px;")
        value_widget.setAlignment(Qt.AlignCenter)
        box_layout.addWidget(value_widget)
        
        box.setLayout(box_layout)
        box.value_widget = value_widget  # Store reference for updates
        
        return box
    
    def _refresh(self):
        """Update all dashboard values"""
        try:
            # Get open positions
            open_trades = self.db.get_open_trade_outcomes() if hasattr(self.db, 'get_open_trade_outcomes') else []
            
            # Update open trades count
            self.open_trades_box.value_widget.setText(str(len(open_trades)))
            
            # Get daily metrics
            from trading.daily_pnl_tracker import get_daily_metrics
            metrics = get_daily_metrics(self.db) if hasattr(get_daily_metrics, '__call__') else {}
            
            # Update P&L
            daily_pnl = metrics.get('total_pnl', 0)
            pnl_color = "#2ecc71" if daily_pnl >= 0 else "#e74c3c"
            self.pnl_box.value_widget.setText(f"₹{daily_pnl:,.0f}")
            self.pnl_box.value_widget.setStyleSheet(f"color: {pnl_color}; background-color: #34495e; padding: 8px; border-radius: 3px;")
            
            # Update P&L bar
            self.pnl_bar.setValue(int(daily_pnl))
            
            # Update win rate
            win_rate = metrics.get('win_rate', 0)
            self.win_rate_box.value_widget.setText(f"{win_rate:.1f}%")
            
            # Update daily loss
            daily_loss = abs(daily_pnl) if daily_pnl < 0 else 0
            daily_loss_limit = config.MAX_DAILY_LOSS_RUPEES if hasattr(config, 'MAX_DAILY_LOSS_RUPEES') else 5000
            loss_pct = (daily_loss / daily_loss_limit) * 100 if daily_loss_limit > 0 else 0
            self.daily_loss_box.value_widget.setText(f"₹{daily_loss:,.0f}/₹{daily_loss_limit:,.0f}")
            
            loss_color = "#e74c3c" if loss_pct > 80 else "#f39c12" if loss_pct > 50 else "#2ecc71"
            self.daily_loss_box.value_widget.setStyleSheet(f"color: {loss_color}; background-color: #34495e; padding: 8px; border-radius: 3px;")
            
            # Update positions table
            self._update_positions_table(open_trades)
            
            # Update status
            if hasattr(config, 'LIVE_TRADING_MODE') and config.LIVE_TRADING_MODE:
                self.status_label.setText("🟥 Status: LIVE TRADING ENABLED")
                self.status_label.setStyleSheet("color: #e74c3c; font-style: italic;")
            else:
                self.status_label.setText("🟩 Status: PAPER TRADING (Simulation)")
                self.status_label.setStyleSheet("color: #2ecc71; font-style: italic;")
        
        except Exception as e:
            logger.debug(f"Dashboard refresh error: {e}")
    
    def _update_positions_table(self, trades: list):
        """Update open positions table"""
        self.positions_table.setRowCount(len(trades))
        
        for row, trade in enumerate(trades):
            try:
                symbol = trade.get('symbol', '?')
                qty = trade.get('quantity', 0)
                entry = trade.get('entry_price', 0)
                
                # Get current price
                current_price = self.order_manager.broker.get_spot_price(trade.get('index_name', 'NIFTY')) if hasattr(self.order_manager, 'broker') else entry
                
                # Calculate P&L
                pnl = (current_price - entry) * qty * 65  # Assume NIFTY lot size
                direction = trade.get('direction', 'N/A')
                entry_time = trade.get('entry_time', '')
                
                # Add to table
                self.positions_table.setItem(row, 0, QTableWidgetItem(symbol))
                self.positions_table.setItem(row, 1, QTableWidgetItem(f"{qty}"))
                self.positions_table.setItem(row, 2, QTableWidgetItem(f"{entry:,.0f}"))
                self.positions_table.setItem(row, 3, QTableWidgetItem(f"{current_price:,.0f}"))
                
                pnl_item = QTableWidgetItem(f"₹{pnl:,.0f}")
                pnl_item.setForeground(QColor("#2ecc71" if pnl >= 0 else "#e74c3c"))
                self.positions_table.setItem(row, 4, pnl_item)
                
                self.positions_table.setItem(row, 5, QTableWidgetItem(direction))
                self.positions_table.setItem(row, 6, QTableWidgetItem(str(entry_time)))
            
            except Exception as e:
                logger.debug(f"Error updating position row: {e}")
    
    def _emergency_exit(self):
        """Close ALL open positions immediately"""
        reply = QMessageBox.warning(
            self,
            "EMERGENCY EXIT?",
            "Close ALL open positions immediately?\n\n"
            "This will place market sell orders for all positions.\n"
            "You may incur losses if markets are gapping.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # Default to No (safer)
        )
        
        if reply == QMessageBox.Yes:
            logger.critical("🚨 EMERGENCY EXIT ACTIVATED!")
            self.emergency_exit_clicked.emit()
            
            try:
                open_trades = self.db.get_open_trade_outcomes() if hasattr(self.db, 'get_open_trade_outcomes') else []
                
                for trade in open_trades:
                    try:
                        logger.critical(f"Closing position: {trade['symbol']}")
                        # Execute close order via order_manager
                        if hasattr(self.order_manager, '_execute_emergency_close'):
                            self.order_manager._execute_emergency_close(trade['broker_order_id'])
                    
                    except Exception as e:
                        logger.error(f"Failed to close {trade['symbol']}: {e}")
                
                QMessageBox.information(self, "Success", "Emergency exit completed.")
            
            except Exception as e:
                logger.error(f"Emergency exit error: {e}")
                QMessageBox.critical(self, "Error", f"Emergency exit failed: {e}")
    
    def closeEvent(self, event):
        """Clean up when dashboard closes"""
        self.timer.stop()
        super().closeEvent(event)
