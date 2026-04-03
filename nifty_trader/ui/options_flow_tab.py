"""
ui/options_flow_tab.py
Tab 3 — Options Flow
Full option chain display with PCR, OI heatmap, Max Pain.
"""

import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QFrame, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush

import config

logger = logging.getLogger(__name__)


def _item(text, color="#c9d1d9", bg=None, bold=False, center=True):
    it = QTableWidgetItem(str(text))
    it.setForeground(QColor(color))
    if bg:
        it.setBackground(QColor(bg))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


class OptionsFlowTab(QWidget):

    def __init__(self, data_manager):
        super().__init__()
        self._dm  = data_manager
        self._current_index = config.INDICES[0]
        self._current_expiry_ts = 0  # 0 = nearest/primary
        self._expiries_list = []    # Available expiries from broker
        self._build_ui()
        self._load_expiries()
        self.refresh()  # Load initial data

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Controls
        ctrl = QHBoxLayout()
        title = QLabel("OPTIONS CHAIN — SMART MONEY FLOW")
        title.setStyleSheet("color: #58a6ff; font-size: 14px; font-weight: bold;")
        self._idx_combo = QComboBox()
        self._idx_combo.addItems(config.INDICES)
        self._idx_combo.currentTextChanged.connect(self._on_index_changed)
        
        # Expiry selector
        self._expiry_combo = QComboBox()
        self._expiry_combo.currentIndexChanged.connect(self._on_expiry_changed)
        
        ctrl.addWidget(title)
        ctrl.addStretch()
        ctrl.addWidget(QLabel("Index:"))
        ctrl.addWidget(self._idx_combo)
        ctrl.addSpacing(20)
        ctrl.addWidget(QLabel("Expiry:"))
        ctrl.addWidget(self._expiry_combo)
        layout.addLayout(ctrl)

        # Metrics bar
        metrics = QFrame()
        metrics.setStyleSheet("background: #161b22; border: 1px solid #30363d; border-radius: 4px;")
        ml = QHBoxLayout(metrics)
        ml.setContentsMargins(16, 8, 16, 8)

        self._expiry_lbl  = self._metric_widget(ml, "EXPIRY")
        self._spot_lbl    = self._metric_widget(ml, "SPOT")
        self._pcr_lbl     = self._metric_widget(ml, "PCR (OI)")
        self._pcr_vol_lbl = self._metric_widget(ml, "PCR (VOL)")
        self._maxpain_lbl = self._metric_widget(ml, "MAX PAIN")
        self._total_ce_lbl = self._metric_widget(ml, "TOTAL CALL OI")
        self._total_pe_lbl = self._metric_widget(ml, "TOTAL PUT OI")
        self._oi_sig_lbl  = self._metric_widget(ml, "OI SIGNAL")
        self._atm_iv_lbl  = self._metric_widget(ml, "ATM IV")
        self._iv_skew_lbl = self._metric_widget(ml, "IV SKEW")
        layout.addWidget(metrics)

        # Option chain table
        self._chain_table = QTableWidget()
        self._chain_table.setColumnCount(10)
        self._chain_table.setHorizontalHeaderLabels([
            "CALL OI", "Δ CALL OI", "CALL VOL", "CALL IV", "CALL LTP",
            "STRIKE",
            "PUT LTP", "PUT IV", "PUT VOL", "Δ PUT OI", # PUT OI shown by color
        ])
        hdr = self._chain_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self._chain_table)

    def _metric_widget(self, parent_layout, label):
        container = QFrame()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        lbl_key = QLabel(label)
        lbl_key.setStyleSheet("color: #8b949e; font-size: 9px; letter-spacing: 0.5px;")
        lbl_val = QLabel("--")
        lbl_val.setStyleSheet("color: #e6edf3; font-size: 13px; font-weight: bold;")
        cl.addWidget(lbl_key)
        cl.addWidget(lbl_val)
        parent_layout.addWidget(container)
        parent_layout.addSpacing(16)
        return lbl_val

    def _on_index_changed(self, text):
        self._current_index = text
        self._load_expiries()
        self.refresh()
    
    def _on_expiry_changed(self, index):
        if index >= 0 and index < len(self._expiries_list):
            self._current_expiry_ts = self._expiries_list[index].get("unix_ts", 0)
        self.refresh()
    
    def _load_expiries(self):
        """Fetch available expiries from broker and populate combo box."""
        idx = self._current_index
        self._expiry_combo.blockSignals(True)
        self._expiry_combo.clear()
        self._expiries_list = []
        
        try:
            expiries = self._dm.get_available_expiries(idx)
            if expiries:
                self._expiries_list = expiries
                logger.info(f"Loaded {len(expiries)} expiries for {idx}")
                for exp in expiries:
                    # Format: "12-Apr-2026 (2d) [Weekly/Monthly]"
                    exp_type = exp.get('type', 'Weekly')
                    label = f"{exp['date']} ({exp['dte']}d) [{exp_type}]"
                    self._expiry_combo.addItem(label)
                # Default to first (nearest) expiry
                self._current_expiry_ts = expiries[0].get("unix_ts", 0)
            else:
                self._expiry_combo.addItem("Primary")
                self._current_expiry_ts = 0
        except Exception as e:
            logger.debug(f"Error loading expiries: {e}")
            self._expiry_combo.addItem("Primary")
            self._current_expiry_ts = 0
        
        self._expiry_combo.blockSignals(False)

    def refresh(self):
        idx   = self._current_index
        # Fetch option chain for selected expiry (0 = primary/nearest)
        chain = self._dm.get_option_chain(idx, expiry_ts=self._current_expiry_ts)
        spot  = self._dm.get_spot(idx)

        if not chain:
            logger.warning(f"No option chain data available for {idx} (expiry_ts={self._current_expiry_ts})")
            # Show empty state
            self._chain_table.setRowCount(0)
            self._expiry_lbl.setText("-- NO DATA --")
            self._spot_lbl.setText(f"₹{spot:,.2f}" if spot and spot > 0 else "--")
            for lbl in [self._pcr_lbl, self._pcr_vol_lbl, self._maxpain_lbl, 
                        self._total_ce_lbl, self._total_pe_lbl, self._oi_sig_lbl,
                        self._atm_iv_lbl, self._iv_skew_lbl]:
                lbl.setText("--")
            return

        # Update metrics
        pcr_color     = "#3fb950" if chain.pcr > 1.2 else "#f85149" if chain.pcr < 0.8 else "#f0883e"
        # Expiry
        if chain.expiry:
            try:
                exp_date = datetime.strptime(chain.expiry, "%d-%b-%Y").date()
                days_left = (exp_date - datetime.today().date()).days
                self._expiry_lbl.setText(f"{chain.expiry} ({days_left}d)")
                exp_color = "#f85149" if days_left <= 1 else "#f0883e" if days_left <= 3 else "#c9d1d9"
                self._expiry_lbl.setStyleSheet(f"color: {exp_color}; font-size: 13px; font-weight: bold;")
            except ValueError:
                self._expiry_lbl.setText(chain.expiry)
        self._spot_lbl.setText(f"₹{spot:,.2f}")
        self._pcr_lbl.setText(f"{chain.pcr:.3f}")
        self._pcr_lbl.setStyleSheet(f"color: {pcr_color}; font-size: 13px; font-weight: bold;")
        self._pcr_vol_lbl.setText(f"{chain.pcr_volume:.3f}")
        self._maxpain_lbl.setText(f"₹{chain.max_pain:,.0f}")
        self._total_ce_lbl.setText(f"{int(chain.total_call_oi / 1e5):.1f}L")
        self._total_pe_lbl.setText(f"{int(chain.total_put_oi / 1e5):.1f}L")

        oi_direction = "BULLISH" if chain.pcr > 1.1 else "BEARISH" if chain.pcr < 0.9 else "NEUTRAL"
        oi_color = "#3fb950" if oi_direction == "BULLISH" else "#f85149" if oi_direction == "BEARISH" else "#f0883e"
        self._oi_sig_lbl.setText(oi_direction)
        self._oi_sig_lbl.setStyleSheet(f"color: {oi_color}; font-size: 13px; font-weight: bold;")

        # ATM IV and IV Skew
        atm = chain.atm_strike
        atm_strikes = [s for s in chain.strikes if abs(s.strike - atm) <= config.ATM_STRIKE_RANGE * 2]
        if atm_strikes:
            atm_s = min(atm_strikes, key=lambda s: abs(s.strike - atm))
            atm_iv = (atm_s.call_iv + atm_s.put_iv) / 2
            iv_skew = atm_s.put_iv / atm_s.call_iv if atm_s.call_iv > 0 else 1.0
            self._atm_iv_lbl.setText(f"{atm_iv:.1f}%")
            skew_color = "#f85149" if iv_skew > 1.15 else "#3fb950" if iv_skew < 0.87 else "#f0883e"
            self._iv_skew_lbl.setText(f"{iv_skew:.2f}x")
            self._iv_skew_lbl.setStyleSheet(f"color: {skew_color}; font-weight: bold;")

        # Build chain table
        strikes = sorted(chain.strikes, key=lambda s: s.strike, reverse=True)
        atm = chain.atm_strike
        max_call_oi = max((s.call_oi for s in chain.strikes), default=1)
        max_put_oi  = max((s.put_oi  for s in chain.strikes), default=1)

        def _fmt_oi(v): return f"{v/1000:.1f}K" if v >= 1000 else str(v)
        def _fmt_ch(v): return f"{v/1000:+.1f}K" if abs(v) >= 1000 else f"{int(v):+d}"

        self._chain_table.setRowCount(len(strikes))
        for row_idx, s in enumerate(strikes):
            is_atm    = s.strike == atm
            is_itm_c  = s.strike < spot
            is_itm_p  = s.strike > spot

            # ATM highlight
            row_bg = "#1c2128" if is_atm else None

            # Call side intensity
            c_intensity = int((s.call_oi / max_call_oi) * 60)
            p_intensity = int((s.put_oi  / max_put_oi)  * 60)
            call_bg = f"#00{c_intensity:02x}00" if c_intensity > 10 else None
            put_bg  = f"#{p_intensity:02x}0000" if p_intensity > 10 else None

            delta_c_color = "#3fb950" if s.call_oi_change > 0 else "#f85149"
            delta_p_color = "#3fb950" if s.put_oi_change  > 0 else "#f85149"
            call_ltp_color = "#8b949e" if is_itm_p else "#c9d1d9"
            put_ltp_color  = "#8b949e" if is_itm_c else "#c9d1d9"

            self._chain_table.setItem(row_idx, 0, _item(_fmt_oi(s.call_oi), "#c9d1d9", bg=call_bg))
            self._chain_table.setItem(row_idx, 1, _item(_fmt_ch(s.call_oi_change), delta_c_color))
            self._chain_table.setItem(row_idx, 2, _item(_fmt_oi(s.call_volume), "#8b949e"))
            self._chain_table.setItem(row_idx, 3, _item(f"{s.call_iv:.1f}%", "#f0883e"))
            self._chain_table.setItem(row_idx, 4, _item(f"{s.call_ltp:.2f}", call_ltp_color))

            # Strike (center, ATM highlighted)
            strike_txt  = f"★ {int(s.strike):,}" if is_atm else f"{int(s.strike):,}"
            strike_color = "#f0883e" if is_atm else "#c9d1d9"
            strike_bg    = "#2d2208" if is_atm else row_bg
            self._chain_table.setItem(row_idx, 5, _item(strike_txt, strike_color,
                                                          bg=strike_bg, bold=is_atm))

            self._chain_table.setItem(row_idx, 6, _item(f"{s.put_ltp:.2f}", put_ltp_color))
            self._chain_table.setItem(row_idx, 7, _item(f"{s.put_iv:.1f}%", "#f0883e"))
            self._chain_table.setItem(row_idx, 8, _item(_fmt_oi(s.put_volume), "#8b949e"))
            self._chain_table.setItem(row_idx, 9, _item(_fmt_ch(s.put_oi_change), delta_p_color))

            if row_bg:
                for col in range(10):
                    item = self._chain_table.item(row_idx, col)
                    if item and not item.background().color().isValid():
                        item.setBackground(QColor(row_bg))
