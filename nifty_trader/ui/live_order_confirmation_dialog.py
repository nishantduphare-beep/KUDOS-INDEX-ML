"""
Live Order Confirmation Dialog — User must manually confirm before REAL money is risked.

Prevents accidental orders via explicit confirmation modal.
Default focus on CANCEL button (safer UX).
Large red warning styling.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QTextEdit, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger(__name__)


class LiveOrderConfirmationDialog(QDialog):
    """Modal confirmation dialog for REAL money orders"""
    
    # Signals
    order_confirmed = Signal()
    order_cancelled = Signal()
    
    def __init__(self, order_details: dict, parent=None):
        super().__init__(parent)
        self.order = order_details
        self._confirmed = False
        
        self.setWindowTitle("⚠️  LIVE ORDER CONFIRMATION - REAL MONEY")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)  # Always on top
        self.setStyleSheet("""
            QDialog {
                background-color: #2c3e50;
                border: 3px solid #e74c3c;
            }
            QLabel {
                color: white;
            }
        """)
        
        self._setup_ui()
        self.resize(500, 400)
    
    def _setup_ui(self):
        """Build UI layout"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # ─────────────────────────────────────────────────────────────────
        # BIG RED WARNING
        # ─────────────────────────────────────────────────────────────────
        warning = QLabel("🚨 REAL MONEY ORDER 🚨")
        warning_font = QFont()
        warning_font.setPointSize(18)
        warning_font.setBold(True)
        warning.setFont(warning_font)
        warning.setStyleSheet("color: #e74c3c; background-color: #34495e; padding: 10px;")
        warning.setAlignment(Qt.AlignCenter)
        layout.addWidget(warning)
        
        # ─────────────────────────────────────────────────────────────────
        # CONFIRMATION REQUIRED
        # ─────────────────────────────────────────────────────────────────
        confirm_msg = QLabel(
            "You must EXPLICITLY CONFIRM to proceed.\n"
            "This will place a REAL MONEY order on Fyers.\n"
            "You can LOSE money if the trade goes against you."
        )
        confirm_msg.setStyleSheet("color: #f39c12; font-weight: bold; padding: 10px;")
        confirm_msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(confirm_msg)
        
        # ─────────────────────────────────────────────────────────────────
        # ORDER DETAILS
        # ─────────────────────────────────────────────────────────────────
        details_label = QLabel("Order Details:")
        details_label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(details_label)
        
        details_text = self._format_order_details()
        details_display = QTextEdit()
        details_display.setText(details_text)
        details_display.setReadOnly(True)
        details_display.setStyleSheet("""
            QTextEdit {
                background-color: #34495e;
                color: #ecf0f1;
                border: 1px solid #7f8c8d;
                font-family: Courier;
                font-size: 10pt;
            }
        """)
        details_display.setMinimumHeight(120)
        layout.addWidget(details_display)
        
        # ─────────────────────────────────────────────────────────────────
        # BUTTONS (Cancel is default focus + highlighted)
        # ─────────────────────────────────────────────────────────────────
        button_layout = QHBoxLayout()
        
        # CANCEL button (left, red, default focus)
        btn_cancel = QPushButton("❌ CANCEL - Don't Place")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
                font-size: 12pt;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #a93226;
            }
            QPushButton:pressed {
                background-color: #922b21;
            }
        """)
        btn_cancel.setFocus()  # Default focus on cancel (safer)
        btn_cancel.setMinimumHeight(50)
        btn_cancel.clicked.connect(self._on_cancel)
        button_layout.addWidget(btn_cancel)
        
        # Spacer
        button_layout.addSpacing(10)
        
        # CONFIRM button (right, green, requires deliberate click)
        btn_confirm = QPushButton("✓ CONFIRM - Place Live Order")
        btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                font-size: 12pt;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        btn_confirm.setMinimumHeight(50)
        btn_confirm.clicked.connect(self._on_confirm)
        button_layout.addWidget(btn_confirm)
        
        layout.addLayout(button_layout)
        
        # ─────────────────────────────────────────────────────────────────
        # FINAL CONFIRMATION CHECKBOX
        # ─────────────────────────────────────────────────────────────────
        final_msg = QLabel(
            "⚠️  Clicking CONFIRM places a REAL money order immediately.\n"
            "This action CANNOT be undone.\n"
            "Losses are possible."
        )
        final_msg.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 10px;")
        final_msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(final_msg)
        
        self.setLayout(layout)
    
    def _format_order_details(self) -> str:
        """Format order details for display"""
        details = []
        details.append("=" * 50)
        details.append("ORDER DETAILS")
        details.append("=" * 50)
        details.append(f"Symbol:       {self.order.get('symbol', '?')}")
        details.append(f"Quantity:     {self.order.get('quantity', '?')} lots")
        details.append(f"Direction:    {self.order.get('direction', '?')}")
        details.append(f"Entry Price:  {self.order.get('entry_price', '?')}")
        details.append(f"Stop Loss:    {self.order.get('stop_loss', '?')}")
        details.append(f"Target T1:    {self.order.get('target_t1', '?')}")
        details.append(f"Target T2:    {self.order.get('target_t2', '?')}")
        details.append(f"Target T3:    {self.order.get('target_t3', '?')}")
        details.append(f"ML Confidence: {self.order.get('ml_confidence', '?'):.2%}")
        details.append("=" * 50)
        return "\n".join(details)
    
    def _on_confirm(self):
        """User confirmed - place order"""
        # Double-check with aggressive warning
        reply = QMessageBox.warning(
            self,
            "FINAL CONFIRMATION",
            "Are you ABSOLUTELY SURE?\n\n"
            "This will IMMEDIATELY place a REAL MONEY order.\n"
            "You understand THE RISK involved?\n\n"
            "Click 'Yes' to confirm, 'No' to cancel.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # Default to No (safer)
        )
        
        if reply == QMessageBox.Yes:
            self._confirmed = True
            logger.critical(f"✓ User confirmed LIVE order: {self.order['symbol']}")
            self.order_confirmed.emit()
            self.accept()
    
    def _on_cancel(self):
        """User cancelled"""
        logger.info(f"User cancelled order: {self.order['symbol']}")
        self.order_cancelled.emit()
        self.reject()
    
    def is_confirmed(self) -> bool:
        """Check if order was confirmed by user"""
        return self._confirmed


def show_live_order_confirmation(order_details: dict, parent=None) -> bool:
    """
    Show confirmation dialog and return whether user confirmed.
    
    Args:
        order_details: Dict with order parameters
        parent: Parent widget
    
    Returns:
        True if user confirmed, False if cancelled
    """
    dialog = LiveOrderConfirmationDialog(order_details, parent)
    result = dialog.exec()
    return result == QDialog.Accepted and dialog.is_confirmed()
