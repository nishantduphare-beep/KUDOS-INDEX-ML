"""
ui/dashboard_tab.py
Tab 1 — Dashboard
Shows real-time index overview for NIFTY, BANKNIFTY, MIDCPNIFTY.
"""

import threading
from datetime import datetime
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QBrush

import config


def _classify_oi(futures_df: pd.DataFrame, minutes: int):
    """
    Returns (fut_price, oi_now, oi_chg_pct, nature, color).
    OI nature:
      Price↑ + OI↑ → LONG BUILDUP   (bullish)
      Price↑ + OI↓ → SHORT COVERING (bullish)
      Price↓ + OI↑ → SHORT BUILDUP  (bearish)
      Price↓ + OI↓ → LONG UNWINDING (bearish)
      else          → NEUTRAL
    """
    if futures_df is None or len(futures_df) < 2:
        return 0.0, 0.0, 0.0, "NO DATA", "#484f58"

    cur = futures_df.iloc[-1]
    fut_price = float(cur["close"])
    oi_now    = float(cur.get("oi", 0))

    cutoff = cur["timestamp"] - pd.Timedelta(minutes=minutes)
    hist   = futures_df[futures_df["timestamp"] <= cutoff]
    ref    = hist.iloc[-1] if len(hist) > 0 else futures_df.iloc[0]

    price_chg = (float(cur["close"]) - float(ref["close"])) / float(ref["close"]) \
                if float(ref["close"]) > 0 else 0.0
    ref_oi    = float(ref.get("oi", 0))
    oi_chg    = (oi_now - ref_oi) / ref_oi if ref_oi > 0 else 0.0
    oi_chg_pct = oi_chg * 100

    P = 0.0008   # price threshold 0.08 %
    O = 0.003    # OI threshold 0.3 %
    p_up  = price_chg >  P
    p_dn  = price_chg < -P
    o_up  = oi_chg    >  O
    o_dn  = oi_chg    < -O

    if   p_up and o_up:  return fut_price, oi_now, oi_chg_pct, "▲ LONG BUILDUP",   "#3fb950"
    elif p_up and o_dn:  return fut_price, oi_now, oi_chg_pct, "▲ SHORT COVERING",  "#58a6ff"
    elif p_dn and o_up:  return fut_price, oi_now, oi_chg_pct, "▼ SHORT BUILDUP",   "#f85149"
    elif p_dn and o_dn:  return fut_price, oi_now, oi_chg_pct, "▼ LONG UNWINDING",  "#f0883e"
    else:                return fut_price, oi_now, oi_chg_pct, "◆ NEUTRAL",          "#8b949e"


def _label(text="", bold=False, size=12, color="#c9d1d9", align=Qt.AlignLeft):
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color};")
    lbl.setAlignment(align)
    return lbl


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #30363d;")
    return line


class IndexCard(QFrame):
    """Self-contained card for one index."""

    def __init__(self, index_name: str, parent=None):
        super().__init__(parent)
        self.index_name = index_name
        self.setObjectName("IndexCard")
        self.setStyleSheet("""
            #IndexCard {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        self._name_lbl  = _label(self.index_name, bold=True, size=12, color="#58a6ff")
        self._live_dot  = _label("●", bold=True, size=9, color="#3fb950")
        hdr.addWidget(self._name_lbl)
        hdr.addStretch()
        hdr.addWidget(self._live_dot)
        layout.addLayout(hdr)

        layout.addWidget(_hline())

        # Price row
        price_row = QHBoxLayout()
        self._price_lbl = _label("--", bold=True, size=18, color="#e6edf3",
                                  align=Qt.AlignLeft)
        self._chg_lbl   = _label("--", bold=True, size=11, color="#3fb950")
        price_row.addWidget(self._price_lbl)
        price_row.addStretch()
        price_row.addWidget(self._chg_lbl)
        layout.addLayout(price_row)

        # Metrics grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnMinimumWidth(0, 100)
        grid.setColumnStretch(1, 1)

        self._bias_val       = self._metric_pair(grid, 0, "MOMENTUM BIAS")
        self._compress_val   = self._metric_pair(grid, 1, "COMPRESSION")
        self._pcr_val        = self._metric_pair(grid, 2, "PCR")
        self._maxpain_val    = self._metric_pair(grid, 3, "MAX PAIN")
        self._plus_di_val    = self._metric_pair(grid, 4, "+DI")
        self._minus_di_val   = self._metric_pair(grid, 5, "-DI")
        self._adx_val        = self._metric_pair(grid, 6, "ADX")
        self._vol_ratio_val  = self._metric_pair(grid, 7, "VOL RATIO")
        self._atr_val        = self._metric_pair(grid, 8, "ATR")
        self._engines_val    = self._metric_pair(grid, 9, "ENGINES")
        self._conf_val       = self._metric_pair(grid, 10, "CONFIDENCE")
        self._mtf_val        = self._metric_pair(grid, 11, "MTF ALIGN")

        layout.addLayout(grid)
        layout.addWidget(_hline())

        # Early move indicator
        self._signal_lbl = _label("● MONITORING", bold=True, size=11, color="#8b949e")
        self._signal_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._signal_lbl)

    def _metric_pair(self, grid, row, key_text):
        key = _label(key_text, bold=False, size=9, color="#8b949e")
        key.setMinimumWidth(100)
        key.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        val = _label("--", bold=True, size=10, color="#c9d1d9")
        grid.addWidget(key, row, 0)
        grid.addWidget(val, row, 1)
        return val

    def update(self, dm):
        """Refresh all metrics from data manager."""
        df    = dm.get_df(self.index_name)
        chain = dm.get_option_chain(self.index_name)
        spot  = dm.get_spot(self.index_name)

        if spot:
            self._price_lbl.setText(f"₹ {spot:,.2f}")

        # Day change — runs whenever spot + any reference is available
        if spot:
            prev_close = dm.get_prev_close(self.index_name)
            ref = None
            if prev_close and prev_close > 0:
                ref = prev_close
            # M3 fix: do NOT use df.iloc[0]["open"] as fallback — that's today's
            # first candle open, not yesterday's close. Skip if prev_close missing.
            if ref:
                change = spot - ref
                pct    = (change / ref) * 100
                color  = "#3fb950" if change >= 0 else "#f85149"
                sign   = "+" if change >= 0 else ""
                self._chg_lbl.setText(f"{sign}{change:.2f} ({sign}{pct:.2f}%)")
                self._chg_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

        if df is not None and len(df) >= 2:
            last = df.iloc[-1]

            plus_di  = float(last.get("plus_di", 0))
            minus_di = float(last.get("minus_di", 0))
            adx      = float(last.get("adx", 0))
            vol_ratio = float(last.get("volume_ratio", 1.0))

            # Bias
            if plus_di > minus_di + 3:
                bias_txt   = "▲ BULLISH"
                bias_color = "#3fb950"
            elif minus_di > plus_di + 3:
                bias_txt   = "▼ BEARISH"
                bias_color = "#f85149"
            else:
                bias_txt   = "◆ NEUTRAL"
                bias_color = "#f0883e"
            self._bias_val.setText(bias_txt)
            self._bias_val.setStyleSheet(f"color: {bias_color}; font-weight: bold;")

            # ADX / DI
            self._plus_di_val.setText(f"{plus_di:.1f}")
            self._minus_di_val.setText(f"{minus_di:.1f}")
            self._adx_val.setText(f"{adx:.1f}")
            self._vol_ratio_val.setText(
                f"{vol_ratio:.2f}x"
            )
            vr_color = "#f0883e" if vol_ratio >= 1.5 else "#8b949e"
            self._vol_ratio_val.setStyleSheet(f"color: {vr_color}; font-weight: bold;")

            atr_val = float(last.get("atr", 0))
            self._atr_val.setText(f"{atr_val:.2f}")

            # Compression — inline check using existing df columns (no engine import)
            atr_v = float(last.get("atr", 0))
            hi    = float(last.get("high", 0))
            lo    = float(last.get("low",  0))
            rng   = hi - lo
            if atr_v > 0 and rng < atr_v * 0.55:
                self._compress_val.setText("⚡ COMPRESSED")
                self._compress_val.setStyleSheet("color: #f0883e; font-weight: bold;")
            else:
                self._compress_val.setText("○ NORMAL")
                self._compress_val.setStyleSheet("color: #8b949e;")

        if chain:
            self._pcr_val.setText(f"{chain.pcr:.3f}")
            pcr_color = "#3fb950" if chain.pcr > 1.2 else "#f85149" if chain.pcr < 0.8 else "#f0883e"
            self._pcr_val.setStyleSheet(f"color: {pcr_color}; font-weight: bold;")
            self._maxpain_val.setText(f"₹ {chain.max_pain:,.0f}")

        # MTF display is updated via set_mtf_result() called from background thread

    def set_engine_status(self, engines_count: int, confidence: float):
        self._engines_val.setText(f"{engines_count}/7")
        eng_color = "#3fb950" if engines_count >= 4 else "#f0883e" if engines_count >= 3 else "#8b949e"
        self._engines_val.setStyleSheet(f"color: {eng_color}; font-weight: bold;")
        self._conf_val.setText(f"{confidence:.1f}%")
        conf_color = "#3fb950" if confidence >= 60 else "#f0883e" if confidence >= 40 else "#8b949e"
        self._conf_val.setStyleSheet(f"color: {conf_color}; font-weight: bold;")

    def set_mtf_result(self, bias_5m: str, bias_15m: str, alignment: str):
        _colors = {
            "STRONG":   "#3fb950",
            "PARTIAL":  "#a8ff78",
            "NEUTRAL":  "#8b949e",
            "WEAK":     "#f0883e",
            "OPPOSING": "#f85149",
        }
        _b5  = "▲" if bias_5m  == "BULLISH" else "▼" if bias_5m  == "BEARISH" else "◆"
        _b15 = "▲" if bias_15m == "BULLISH" else "▼" if bias_15m == "BEARISH" else "◆"
        self._mtf_val.setText(f"{_b5}5m {_b15}15m {alignment}")
        self._mtf_val.setStyleSheet(
            f"color: {_colors.get(alignment, '#8b949e')}; font-weight: bold;"
        )

    def set_signal(self, alert_type: str, direction: str):
        """Highlight the signal state."""
        if alert_type == "TRADE_SIGNAL":
            color  = "#f85149" if direction == "BEARISH" else "#3fb950"
            symbol = "▼" if direction == "BEARISH" else "▲"
            self._signal_lbl.setText(f"🎯 TRADE SIGNAL {symbol} {direction}")
            self._signal_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 12px;"
            )
            self.setStyleSheet("""
                #IndexCard {
                    background: #161b22;
                    border: 2px solid #f0883e;
                    border-radius: 6px;
                }
            """)
        elif alert_type == "EARLY_MOVE":
            color = "#f0883e"
            self._signal_lbl.setText(f"⚡ EARLY MOVE DETECTED — {direction}")
            self._signal_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 11px;"
            )
        else:
            self._signal_lbl.setText("● MONITORING")
            self._signal_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
            self.setStyleSheet("""
                #IndexCard {
                    background: #161b22;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                }
            """)


class FuturesPanel(QFrame):
    """
    Dedicated table showing futures price, OI, and OI nature
    for all indices across 5 / 15 / 30 min timeframes.
    Columns: INDEX | FUT PRICE | OI | 5 MIN | 15 MIN | 30 MIN
    """

    _TIMEFRAMES = [5, 15, 30]
    _COLS = ["INDEX", "FUT PRICE", "OI (L)", "5 MIN", "15 MIN", "30 MIN"]
    _TF_COL = {5: 3, 15: 4, 30: 5}   # timeframe → column index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FuturesPanel")
        self.setStyleSheet("""
            #FuturesPanel {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(_label("INDEX FUTURES", bold=True, size=12, color="#58a6ff"))
        hdr_row.addStretch()
        hdr_row.addWidget(_label("5 MIN / 15 MIN / 30 MIN  OI CHANGE", size=10, color="#484f58"))
        layout.addLayout(hdr_row)

        n_rows = len(config.INDICES)
        n_cols = len(self._COLS)

        self._table = QTableWidget(n_rows, n_cols)
        self._table.setHorizontalHeaderLabels(self._COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #0d1117;
                color: #c9d1d9;
                font-size: 11px;
                border: none;
                gridline-color: #21262d;
            }
            QHeaderView::section {
                background: #161b22;
                color: #8b949e;
                font-size: 10px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #30363d;
                padding: 4px 8px;
            }
            QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #21262d; }
        """)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # INDEX
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)   # FUT PRICE
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)   # OI
        for col in [3, 4, 5]:
            hh.setSectionResizeMode(col, QHeaderView.Stretch)

        self._table.setFixedHeight(30 + n_rows * 52)

        # Pre-fill index column
        for row, idx in enumerate(config.INDICES):
            item = QTableWidgetItem(idx)
            item.setForeground(Qt.white)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self._table.setItem(row, 0, item)
            self._table.setRowHeight(row, 52)

        layout.addWidget(self._table)

    def _make_item(self, text: str, color: str = "#c9d1d9", bold: bool = False,
                   align=Qt.AlignCenter) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QBrush(QColor(color)))
        item.setTextAlignment(align)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    def update_row(self, row: int, futures_df):
        """Update one index row with data from its futures DataFrame."""
        if futures_df is None or len(futures_df) < 2:
            for col in range(1, 6):
                self._table.setItem(row, col, self._make_item("--", "#484f58"))
            return

        cur = futures_df.iloc[-1]
        fut_price = float(cur["close"])
        oi_now    = float(cur.get("oi", 0))

        # FUT PRICE
        self._table.setItem(row, 1,
            self._make_item(f"₹{fut_price:,.2f}", "#e6edf3", bold=True))

        # OI in Lakhs
        if oi_now > 0:
            oi_l = oi_now / 100_000
            self._table.setItem(row, 2,
                self._make_item(f"{oi_l:.1f}L", "#c9d1d9"))
        else:
            self._table.setItem(row, 2, self._make_item("--", "#484f58"))

        # Timeframe columns
        for tf, col in self._TF_COL.items():
            _, _, oi_chg_pct, nature, ncolor = _classify_oi(futures_df, tf)
            sign = "+" if oi_chg_pct >= 0 else ""
            chg_str = f"{sign}{oi_chg_pct:.2f}%"
            cell_text = f"{chg_str}\n{nature}"
            self._table.setItem(row, col,
                self._make_item(cell_text, ncolor, bold=True))


class DashboardTab(QWidget):

    # Emitted when user clicks Connect / Disconnect from dashboard
    connection_requested = Signal(str)   # broker name, or "" for disconnect

    def __init__(self, data_manager):
        super().__init__()
        self._dm           = data_manager
        self._cards: dict  = {}
        self._connecting   = False
        self._build_ui()

        # Refresh token expiry display every 60 s
        self._expiry_timer = QTimer()
        self._expiry_timer.timeout.connect(self._refresh_conn_bar)
        self._expiry_timer.start(60_000)
        self._refresh_conn_bar()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Connection bar ────────────────────────────────────────
        conn_bar = QFrame()
        conn_bar.setObjectName("ConnBar")
        conn_bar.setStyleSheet("""
            #ConnBar {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
            }
        """)
        cb_layout = QHBoxLayout(conn_bar)
        cb_layout.setContentsMargins(14, 7, 14, 7)
        cb_layout.setSpacing(16)

        self._conn_status_lbl = _label("● DISCONNECTED", bold=True, size=11, color="#f85149")
        self._conn_broker_lbl = _label("", size=10, color="#8b949e")
        self._conn_expiry_lbl = _label("", size=10, color="#484f58")

        self._conn_btn = QPushButton("⚡  Connect")
        self._conn_btn.setFixedHeight(28)
        self._conn_btn.setStyleSheet("""
            QPushButton {
                background: #1f6feb; color: white; border: none;
                padding: 4px 18px; border-radius: 3px;
                font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #388bfd; }
            QPushButton:disabled { background: #21262d; color: #484f58; }
        """)
        self._conn_btn.clicked.connect(self._on_conn_btn_clicked)

        cb_layout.addWidget(self._conn_status_lbl)
        cb_layout.addWidget(self._conn_broker_lbl)
        cb_layout.addStretch()
        cb_layout.addWidget(self._conn_expiry_lbl)
        cb_layout.addWidget(self._conn_btn)
        layout.addWidget(conn_bar)

        # ── Header ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = _label("LIVE MARKET DASHBOARD", bold=True, size=14, color="#58a6ff")
        self._last_update_lbl = _label("", size=10, color="#8b949e",
                                        align=Qt.AlignRight)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._last_update_lbl)
        layout.addLayout(hdr)

        # ── Index cards (horizontal) ──────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        for idx in config.INDICES:
            card = IndexCard(idx)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._cards[idx] = card
            cards_row.addWidget(card)
        layout.addLayout(cards_row)

        # ── Futures table ─────────────────────────────────────────
        self._futures_panel = FuturesPanel()
        layout.addWidget(self._futures_panel)

        # ── Market summary bar ────────────────────────────────────
        summary = QFrame()
        summary.setObjectName("SummaryBar")
        summary.setStyleSheet("""
            #SummaryBar {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
            }
        """)
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(16, 8, 16, 8)

        self._summary_labels = {}
        for idx in config.INDICES:
            lbl_key  = _label(f"{idx}:", size=11, color="#8b949e")
            lbl_val  = _label("--", bold=True, size=11, color="#e6edf3")
            summary_layout.addWidget(lbl_key)
            summary_layout.addWidget(lbl_val)
            summary_layout.addSpacing(24)
            self._summary_labels[idx] = lbl_val

        summary_layout.addStretch()
        layout.addWidget(summary)

        layout.addStretch()

    # ── Connection bar helpers ────────────────────────────────────

    def _refresh_conn_bar(self):
        """Update connection bar to reflect current state."""
        if self._dm.is_connected():
            broker = config.BROKER.upper()
            self._conn_status_lbl.setText(f"● LIVE — {broker}")
            self._conn_status_lbl.setStyleSheet("color:#3fb950; font-weight:bold; font-size:11px;")
            self._conn_btn.setText("✕  Disconnect")
            self._conn_btn.setStyleSheet("""
                QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d;
                    padding:4px 18px; border-radius:3px; font-size:11px; font-weight:bold; }
                QPushButton:hover { background:#30363d; }
            """)
            self._conn_btn.setEnabled(True)
            # Token expiry for Fyers
            if config.BROKER == "fyers":
                try:
                    from data.adapters.fyers_adapter import fyers_token_expiry_display
                    self._conn_expiry_lbl.setText(fyers_token_expiry_display())
                    self._conn_expiry_lbl.setStyleSheet("color:#8b949e; font-size:10px;")
                except Exception:
                    pass
            else:
                self._conn_expiry_lbl.setText("")
            self._conn_broker_lbl.setText("")
        else:
            self._conn_status_lbl.setText("● DISCONNECTED")
            self._conn_status_lbl.setStyleSheet("color:#f85149; font-weight:bold; font-size:11px;")
            # Show what saved broker + token state is
            try:
                from data.adapters.fyers_adapter import load_fyers_token, fyers_token_expiry_display
                from auth import credentials as _cred_module
            except Exception:
                pass
            saved_broker = config.BROKER
            if saved_broker == "fyers":
                try:
                    from data.adapters.fyers_adapter import load_fyers_token, fyers_token_expiry_display
                    cached = load_fyers_token()
                    if cached:
                        self._conn_broker_lbl.setText("Fyers")
                        self._conn_broker_lbl.setStyleSheet("color:#f0883e; font-size:10px;")
                        self._conn_expiry_lbl.setText(fyers_token_expiry_display())
                        self._conn_expiry_lbl.setStyleSheet("color:#3fb950; font-size:10px;")
                        self._conn_btn.setText("⚡  Connect  (token ready)")
                        self._conn_btn.setStyleSheet("""
                            QPushButton { background:#238636; color:white; border:none;
                                padding:4px 18px; border-radius:3px; font-size:11px; font-weight:bold; }
                            QPushButton:hover { background:#2ea043; }
                        """)
                    else:
                        self._conn_expiry_lbl.setText("Token expired — go to Credentials tab")
                        self._conn_expiry_lbl.setStyleSheet("color:#f85149; font-size:10px;")
                        self._conn_btn.setText("⚡  Connect")
                        self._conn_btn.setStyleSheet("""
                            QPushButton { background:#1f6feb; color:white; border:none;
                                padding:4px 18px; border-radius:3px; font-size:11px; font-weight:bold; }
                            QPushButton:hover { background:#388bfd; }
                        """)
                except Exception:
                    pass
            elif saved_broker == "mock":
                self._conn_broker_lbl.setText("Mock mode")
                self._conn_broker_lbl.setStyleSheet("color:#f0883e; font-size:10px;")
                self._conn_expiry_lbl.setText("")
                self._conn_btn.setText("⚡  Connect")
                self._conn_btn.setStyleSheet("""
                    QPushButton { background:#1f6feb; color:white; border:none;
                        padding:4px 18px; border-radius:3px; font-size:11px; font-weight:bold; }
                    QPushButton:hover { background:#388bfd; }
                """)
            self._conn_btn.setEnabled(True)

    def _on_conn_btn_clicked(self):
        if self._connecting:
            return
        if self._dm.is_connected():
            # Disconnect
            self._dm.stop()
            self._refresh_conn_bar()
            return
        # Connect using saved token / credentials
        self._conn_btn.setEnabled(False)
        self._conn_btn.setText("Connecting…")
        self._connecting = True
        broker = config.BROKER
        def _do():
            try:
                ok = self._dm.reconnect(broker)
                # Schedule UI update back on main thread
                QTimer.singleShot(0, lambda: self._after_connect(ok))
            except Exception:
                QTimer.singleShot(0, lambda: self._after_connect(False))
        threading.Thread(target=_do, daemon=True, name="DashConnect").start()

    def _after_connect(self, ok: bool):
        self._connecting = False
        self._conn_btn.setEnabled(True)
        self._refresh_conn_bar()
        if ok:
            self.connection_requested.emit(config.BROKER)

    def on_connection_changed(self, connected: bool, broker: str):
        """Called by main window when connection state changes externally."""
        self._refresh_conn_bar()

    def refresh(self):
        """Called by main window timer."""
        now = datetime.now().strftime("%H:%M:%S")
        self._last_update_lbl.setText(f"Updated {now}")

        for idx in config.INDICES:
            card  = self._cards[idx]
            card.update(self._dm)

            spot = self._dm.get_spot(idx)
            if spot:
                self._summary_labels[idx].setText(f"₹{spot:,.2f}")

        # ── Futures table (all indices × all timeframes) ──────────
        for row, idx in enumerate(config.INDICES):
            try:
                fdf = self._dm.get_futures_df(idx)
                self._futures_panel.update_row(row, fdf)
            except Exception:
                pass

    def set_engine_result(self, idx: str, engines_count: int, confidence: float,
                          bias_5m: str = "", bias_15m: str = "", alignment: str = ""):
        """Called from main_window background thread via QTimer.singleShot(0)."""
        card = self._cards.get(idx)
        if card:
            card.set_engine_status(engines_count, confidence)
            if alignment:
                card.set_mtf_result(bias_5m, bias_15m, alignment)

    def on_alert(self, alert_obj):
        """Called when an alert fires — update the relevant card."""
        if hasattr(alert_obj, "index_name"):
            card = self._cards.get(alert_obj.index_name)
            if card:
                card.set_signal(alert_obj.alert_type, alert_obj.direction)
