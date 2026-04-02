"""
Live Trading Disclaimer Dialog — Legal acknowledgment before enabling live trading.

User must:
  1. Read and understand risks
  2. Confirm they accept full responsibility
  3. Acknowledge they've done paper trading
  4. Have sufficient capital
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QPushButton, QLabel, QVBoxLayout, QCheckBox, QScrollArea, QTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class LiveTradingDisclaimerDialog(QDialog):
    """Disclaimer and risk acknowledgment before enabling live trading"""
    
    user_acknowledged = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️  LIVE TRADING DISCLAIMER")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #2c3e50;
                color: #ecf0f1;
            }
            QLabel {
                color: #ecf0f1;
            }
        """)
        
        self._setup_ui()
        self.resize(600, 700)
    
    def _setup_ui(self):
        """Build dialog layout"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ─────────────────────────────────────────────────────────────────
        # TITLE
        # ─────────────────────────────────────────────────────────────────
        title = QLabel("⚠️  LIVE TRADING DISCLAIMER")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #e74c3c;")
        layout.addWidget(title)
        
        # ─────────────────────────────────────────────────────────────────
        # DISCLAIMER TEXT
        # ─────────────────────────────────────────────────────────────────
        disclaimer_text = QTextEdit()
        disclaimer_text.setReadOnly(True)
        disclaimer_text.setStyleSheet("""
            QTextEdit {
                background-color: #34495e;
                color: #ecf0f1;
                border: 1px solid #7f8c8d;
                font-size: 10pt;
            }
        """)
        
        disclaimer_content = """
RISKS & DISCLAIMERS

You are about to enable REAL MONEY TRADING on your Fyers account.

⚠️  UNDERSTAND THE RISKS:

• You can LOSE MONEY - Past performance does not guarantee future results
• Algorithmic trading can FAIL - Systems can malfunction
• Market GAP RISK - Stop-losses may not execute if market gaps beyond them
• TECHNOLOGY FAILURE - Broker API errors, network interruptions, power loss
• MODEL DEGRADATION - ML predictions degrade over time
• SLIPPAGE - Actual entry/exit may be far from predicted levels

🚨 CRITICAL MECHANISMS IN PLACE:

✓ Automatic stop-loss execution (prevents holding losing trades)
✓ Daily loss limit (₹5,000 - stops all trading if exceeded)
✓ Position size limit (1-2 lots only)
✓ Market circuit breaker (stops on ATR spike >300%)
✓ Emergency exit button (closes all positions instantly)
✓ Continuous monitoring dashboard

⚠️  YOU MUST HAVE:

• Minimum ₹50,000 in Fyers account for safe trading
• ₹1,00,000+ RECOMMENDED to avoid forced liquidation
• Tested system in PAPER TRADING for minimum 5 days
• Read and understood all documentation
• Received NO financial advice (this is NOT advice)

YOUR EXPLICIT ACKNOWLEDGMENTS:

1. [ ] I understand I can LOSE MONEY
2. [ ] I accept FULL RESPONSIBILITY for losses
3. [ ] I have paper traded for 5+ days successfully
4. [ ] I have ₹50,000+ available in my Fyers account
5. [ ] I have reviewed all documentation
6. [ ] I understand this is NOT financial advice
7. [ ] I understand market gaps can exceed stop-losses
8. [ ] I am comfortable losing ₹5,000/day before trading stops

THIS IS NOT FINANCIAL ADVICE.

Use this system ONLY if you:
• Understand derivatives trading
• Can afford to lose the capital deployed
• Are comfortable with algorithmic automation
• Accept full responsibility for outcomes

By clicking ACCEPT, you confirm you have read, understood, and agree to
these terms.
        """
        
        disclaimer_text.setText(disclaimer_content)
        layout.addWidget(disclaimer_text)
        
        # ─────────────────────────────────────────────────────────────────
        # CHECKBOXES
        # ─────────────────────────────────────────────────────────────────
        self.checkbox_risks = QCheckBox("☑️  I understand the risks and accept full responsibility")
        self.checkbox_risks.setStyleSheet("color: #ecf0f1; padding: 5px;")
        layout.addWidget(self.checkbox_risks)
        
        self.checkbox_capital = QCheckBox("☑️  I have ₹50,000+ in my Fyers account")
        self.checkbox_capital.setStyleSheet("color: #ecf0f1; padding: 5px;")
        layout.addWidget(self.checkbox_capital)
        
        self.checkbox_paper = QCheckBox("☑️  I have tested paper trading for 5+ days")
        self.checkbox_paper.setStyleSheet("color: #ecf0f1; padding: 5px;")
        layout.addWidget(self.checkbox_paper)
        
        self.checkbox_docs = QCheckBox("☑️  I have read all documentation")
        self.checkbox_docs.setStyleSheet("color: #ecf0f1; padding: 5px;")
        layout.addWidget(self.checkbox_docs)
        
        self.checkbox_advice = QCheckBox("☑️  I understand this is NOT financial advice")
        self.checkbox_advice.setStyleSheet("color: #ecf0f1; padding: 5px;")
        layout.addWidget(self.checkbox_advice)
        
        # ─────────────────────────────────────────────────────────────────
        # BUTTONS
        # ─────────────────────────────────────────────────────────────────
        button_layout = QVBoxLayout()
        
        btn_accept = QPushButton("✓ I ACCEPT - Enable Live Trading")
        btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                font-size: 11pt;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
                color: #7f8c8d;
            }
        """)
        btn_accept.setMinimumHeight(40)
        btn_accept.clicked.connect(self._on_accept)
        button_layout.addWidget(btn_accept)
        
        btn_decline = QPushButton("✗ DECLINE - Keep Paper Trading")
        btn_decline.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                font-size: 11pt;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        btn_decline.setMinimumHeight(40)
        btn_decline.clicked.connect(self.reject)
        button_layout.addWidget(btn_decline)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _on_accept(self):
        """Check all boxes before accepting"""
        if not all([
            self.checkbox_risks.isChecked(),
            self.checkbox_capital.isChecked(),
            self.checkbox_paper.isChecked(),
            self.checkbox_docs.isChecked(),
            self.checkbox_advice.isChecked(),
        ]):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Incomplete", "Please check all boxes to proceed.")
            return
        
        logger.critical("✓ User acknowledged live trading risks and accepted terms")
        self.user_acknowledged.emit()
        self.accept()


def show_live_trading_disclaimer(parent=None) -> bool:
    """
    Show disclaimer dialog.
    
    Args:
        parent: Parent widget
    
    Returns:
        True if user accepts, False if declines
    """
    dialog = LiveTradingDisclaimerDialog(parent)
    result = dialog.exec()
    return result == QDialog.Accepted
