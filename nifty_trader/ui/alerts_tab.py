"""
ui/alerts_tab.py
Tab 4 — Trade Alerts with dual-panel right side:
  • TradeAlertPanel  — instrument card (action, entry, SL, T1/T2/T3)
  • TradeDetailPanel — market context, ML engine, outcome tracking
"""

from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QPushButton, QSplitter, QTextEdit,
    QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

import config
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
    w.setStyleSheet(f"color:{color}; font-size:{size}px;" + (" font-weight:bold;" if bold else ""))
    return w


def _panel_frame(obj_name: str) -> "QFrame":
    f = QFrame()
    f.setObjectName(obj_name)
    f.setStyleSheet(f"#{obj_name} {{ background:#0d1117; border:1px solid #30363d; border-radius:5px; }}")
    return f


# ─────────────────────────────────────────────────────────────────
# ML STATUS PANEL
# ─────────────────────────────────────────────────────────────────
class MLStatusPanel(QFrame):
    """Compact header bar — model phase, samples, metrics."""

    def __init__(self):
        super().__init__()
        self.setObjectName("MLSP")
        self.setStyleSheet("#MLSP { background:#161b22; border:1px solid #30363d; border-radius:5px; }")
        ly = QHBoxLayout(self)
        ly.setContentsMargins(14, 8, 14, 8)
        ly.setSpacing(8)
        lbl_engine = _lbl("🤖 ML ENGINE", "#58a6ff", bold=True, size=11)
        lbl_engine.setFixedWidth(100)
        ly.addWidget(lbl_engine)
        ly.addSpacing(8)

        def _m(label):
            c = QFrame()
            c.setFixedWidth(110)
            cl = QVBoxLayout(c)
            cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(2)
            k = _lbl(label, "#8b949e", size=9)
            v = _lbl("—", "#e6edf3", bold=True, size=12)
            cl.addWidget(k); cl.addWidget(v)
            ly.addWidget(c)
            return v

        self._phase   = _m("PHASE")
        self._samples = _m("LABELED")
        self._version = _m("MODEL")
        self._f1      = _m("F1")
        self._needed  = _m("STILL NEED")
        ly.addStretch()

        self._btn = QPushButton("⟳  Retrain")
        self._btn.setStyleSheet("""
            QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d;
                border-radius:4px; padding:4px 12px; font-size:11px; }
            QPushButton:hover { border-color:#58a6ff; }
        """)
        self._btn.clicked.connect(self._retrain)
        ly.addWidget(self._btn)

    def refresh(self):
        try:
            from ml.model_manager import get_model_manager
            s = get_model_manager().get_status()
            if s["phase"] == 1:
                self._phase.setText("1 — Collecting")
                self._phase.setStyleSheet("color:#f0883e; font-weight:bold; font-size:12px;")
                self._needed.setText(str(s["needed_to_train"]))
            else:
                self._phase.setText("2 — Active ✓")
                self._phase.setStyleSheet("color:#3fb950; font-weight:bold; font-size:12px;")
                self._needed.setText("—")
            self._samples.setText(str(s["labeled_samples"]))
            v = s["model_version"]
            self._version.setText(f"v{v}" if v else "—")
            f1 = s.get("metrics", {}).get("f1", 0)
            self._f1.setText(f"{f1:.3f}" if f1 else "—")
        except Exception:
            pass

    def _retrain(self):
        self._btn.setText("Training…"); self._btn.setEnabled(False)
        import threading
        def _t():
            try:
                from ml.model_manager import get_model_manager
                get_model_manager().force_retrain()
            finally:
                self._btn.setText("⟳  Retrain"); self._btn.setEnabled(True)
        threading.Thread(target=_t, daemon=True).start()


# ─────────────────────────────────────────────────────────────────
# PANEL 1 — TRADE ALERT  (recommendation card)
# ─────────────────────────────────────────────────────────────────
class TradeAlertPanel(QFrame):
    """
    Shows the trade recommendation card:
      action verb, instrument, expiry, strike/type, entry, SL, T1/T2/T3.
    For Early Move alerts: shows the early-move card with a "watching…" notice.
    """

    _EMPTY_HTML = (
        "<div style='color:#484f58;font-size:11px;font-family:Consolas,monospace;"
        "padding:24px 12px;text-align:center'>"
        "No alert selected</div>"
    )

    def __init__(self):
        super().__init__()
        self.setObjectName("TAP")
        self.setStyleSheet(
            "#TAP { background:#0d1117; border:1px solid #30363d; border-radius:5px; }"
        )
        ly = QVBoxLayout(self)
        ly.setContentsMargins(12, 10, 12, 10)
        ly.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("TRADE ALERT", "#58a6ff", bold=True, size=10))
        self._type_badge = _lbl("—", "#484f58", size=10)
        hdr.addStretch()
        hdr.addWidget(self._type_badge)
        ly.addLayout(hdr)

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setStyleSheet(
            "QTextEdit { background:#0d1117; color:#e6edf3; border:none;"
            "font-family:Consolas,monospace; font-size:12px; }"
        )
        ly.addWidget(self._body)
        self._body.setHtml(self._EMPTY_HTML)

    # ── public ────────────────────────────────────────────────────

    def show_alert(self, a):
        from engines.signal_aggregator import TradeSignal
        is_trade = isinstance(a, TradeSignal)
        dc = "#3fb950" if a.direction == "BULLISH" else "#f85149"

        is_confirmed = getattr(a, "is_confirmed", False)

        if is_confirmed:
            self._type_badge.setText("✅ ACTIVATION CONFIRMED")
            self._type_badge.setStyleSheet(
                "color:#ffd700; font-size:10px; font-weight:bold;"
            )
            border_color = "#ffd700"
            bg_color     = "#1a1a00"
        elif is_trade:
            self._type_badge.setText("TRADE SIGNAL")
            self._type_badge.setStyleSheet(
                "color:#3fb950; font-size:10px; font-weight:bold;"
            )
            border_color = "#238636"
            bg_color     = "#0d2010"
        else:
            border_color = "#f0883e"
            bg_color     = "#2d1c08"

        if is_trade or is_confirmed:
            h = (
                f"<div style='background:{bg_color};border:2px solid {border_color};"
                f"border-radius:6px;padding:14px;"
                f"font-family:Consolas,monospace'>"
                # confirmed banner
                + (
                    f"<div style='font-size:10px;color:#ffd700;font-weight:bold;"
                    f"letter-spacing:2px;margin-bottom:6px'>✅ CANDLE CLOSE CONFIRMED</div>"
                    if is_confirmed else ""
                )
                # action verb
                + f"<div style='font-size:24px;font-weight:bold;color:{dc};"
                f"letter-spacing:3px'>{a.action}</div>"
                # instrument line
                f"<div style='font-size:14px;color:#e6edf3;font-weight:bold;"
                f"margin:4px 0 12px'>"
                f"{a.index_name}&nbsp;&nbsp;"
                f"{a.expiry_display}&nbsp;&nbsp;"
                f"{int(a.strike)}&nbsp;{a.option_type}</div>"
                # levels table
                f"<table style='width:100%;border-collapse:collapse'>"
                f"<tr>"
                f"  <td style='color:#8b949e;padding:4px 0;width:60px;font-size:11px'>Entry</td>"
                f"  <td style='color:#e6edf3;font-size:22px;font-weight:bold'>"
                f"    {a.entry_reference:.0f}</td>"
                f"</tr>"
                f"<tr>"
                f"  <td style='color:#8b949e;padding:3px 0;font-size:11px'>SL</td>"
                f"  <td style='color:#f85149;font-size:17px;font-weight:bold'>"
                f"    {a.stop_loss_reference:.0f}</td>"
                f"</tr>"
                f"<tr>"
                f"  <td style='color:#8b949e;padding:3px 0;font-size:11px'>T1</td>"
                f"  <td style='color:#3fb950;font-size:16px;font-weight:bold'>"
                f"    {a.target1:.0f}</td>"
                f"</tr>"
                f"<tr>"
                f"  <td style='color:#8b949e;padding:3px 0;font-size:11px'>T2</td>"
                f"  <td style='color:#3fb950;font-size:16px;font-weight:bold'>"
                f"    {a.target2:.0f}</td>"
                f"</tr>"
                f"<tr>"
                f"  <td style='color:#8b949e;padding:3px 0;font-size:11px'>T3</td>"
                f"  <td style='color:#3fb950;font-size:16px;font-weight:bold'>"
                f"    {a.target3:.0f}</td>"
                f"</tr>"
                f"</table>"
                f"</div>"
            )
        else:
            self._type_badge.setText("EARLY MOVE")
            self._type_badge.setStyleSheet(
                "color:#f0883e; font-size:10px; font-weight:bold;"
            )
            h = (
                f"<div style='background:#2d1c08;border:1px solid #f0883e;"
                f"border-radius:5px;padding:14px;"
                f"font-family:Consolas,monospace'>"
                f"<div style='font-size:14px;font-weight:bold;color:#f0883e;"
                f"letter-spacing:1px'>EARLY MOVE ALERT</div>"
                f"<div style='font-size:16px;color:{dc};font-weight:bold;margin:6px 0'>"
                f"{a.index_name} — {a.direction}</div>"
                f"<div style='color:#8b949e;font-size:10px;margin-top:10px;'>"
                f"⏳ Monitoring for trade signal confirmation…</div>"
                f"</div>"
            )

        self._body.setHtml(h)

    def clear(self):
        self._type_badge.setText("—")
        self._type_badge.setStyleSheet("color:#484f58; font-size:10px;")
        self._body.setHtml(self._EMPTY_HTML)


# ─────────────────────────────────────────────────────────────────
# PANEL 2 — TRADE DETAILS  (context · ML · outcome)
# ─────────────────────────────────────────────────────────────────
class TradeDetailPanel(QFrame):
    """
    Shows market context, ML engine result, MTF alignment,
    and live outcome tracking for the selected alert.
    """

    _EMPTY_HTML = (
        "<div style='color:#484f58;font-size:11px;font-family:Consolas,monospace;"
        "padding:20px 12px;text-align:center'>"
        "Select an alert to see details</div>"
    )

    def __init__(self):
        super().__init__()
        self.setObjectName("TDP")
        self.setStyleSheet(
            "#TDP { background:#0d1117; border:1px solid #30363d; border-radius:5px; }"
        )
        ly = QVBoxLayout(self)
        ly.setContentsMargins(12, 10, 12, 10)
        ly.setSpacing(4)
        ly.addWidget(_lbl("TRADE DETAILS", "#58a6ff", bold=True, size=10))

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setStyleSheet(
            "QTextEdit { background:#0d1117; color:#e6edf3; border:none;"
            "font-family:Consolas,monospace; font-size:12px; }"
        )
        ly.addWidget(self._body)
        self._body.setHtml(self._EMPTY_HTML)

    # ── public ────────────────────────────────────────────────────

    def show_alert(self, a):
        from engines.signal_aggregator import TradeSignal
        is_trade = isinstance(a, TradeSignal)

        def _row(k, v, vc="#c9d1d9"):
            return (
                f"<tr>"
                f"<td style='color:#58a6ff;padding:2px 10px 2px 0;"
                f"white-space:nowrap;vertical-align:top'>{k}</td>"
                f"<td style='color:{vc}'>{v}</td>"
                f"</tr>"
            )

        h = "<div style='font-family:Consolas,monospace;font-size:12px'>"

        # ── MARKET CONTEXT ────────────────────────────────────────
        h += (
            "<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
            "margin:0 0 3px'>MARKET CONTEXT</div>"
            "<table style='width:100%;font-size:11px;border-collapse:collapse'>"
        )
        h += _row("Spot", f"{a.spot_price:,.2f}")
        if is_trade:
            h += _row("ATM Strike", f"{a.atm_strike:,.0f}")
        pcr_c = "#3fb950" if a.pcr > 1.2 else "#f85149" if a.pcr < 0.8 else "#c9d1d9"
        h += _row("PCR", f"{a.pcr:.3f}", pcr_c)
        h += _row("ATR", f"{a.atr:.2f}")
        h += _row("Time", a.timestamp.strftime("%H:%M:%S"))
        h += _row("Engines", ", ".join(a.engines_triggered) or "—", "#f0883e")
        h += _row("Strategy", f"{a.confidence_score:.1f}%", "#e6edf3")
        h += "</table>"

        # ── ML ENGINE ─────────────────────────────────────────────
        ml = getattr(a, "ml_prediction", None)
        h += (
            "<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
            "margin:8px 0 3px'>ML ENGINE</div>"
        )
        if ml is None or not ml.is_available:
            needed = ml.samples_needed if ml else 0
            if needed > 0:
                h += (
                    f"<div style='background:#1c2128;border:1px solid #30363d;"
                    f"border-radius:4px;padding:8px'>"
                    f"<span style='color:#f0883e;font-weight:bold;font-size:11px'>"
                    f"Phase 1 — Collecting Data</span><br>"
                    f"<span style='color:#8b949e;font-size:10px'>"
                    f"<b style='color:#c9d1d9'>{needed}</b> more labeled signals needed."
                    f"</span></div>"
                )
            else:
                h += "<span style='color:#484f58;font-size:11px'>Not available yet</span>"
        else:
            rc = (
                "#3fb950" if "STRONG" in ml.recommendation
                else "#f0883e" if "MODERATE" in ml.recommendation
                else "#8b949e"
            )
            h += (
                f"<div style='background:#0d2818;border:1px solid #238636;"
                f"border-radius:5px;padding:10px'>"
                f"<div style='color:#3fb950;font-weight:bold;font-size:10px;"
                f"letter-spacing:.5px'>ML v{ml.model_version} — {ml.samples_used:,} samples</div>"
                f"<table style='margin-top:4px;width:100%;font-size:11px;border-collapse:collapse'>"
                f"<tr><td style='color:#8b949e;padding:2px 0;width:110px'>ML Confidence</td>"
                f"<td style='color:#e6edf3;font-weight:bold'>{ml.ml_confidence:.1f}%</td></tr>"
                f"<tr><td style='color:#8b949e;padding:2px 0'>Recommendation</td>"
                f"<td style='color:{rc};font-weight:bold'>{ml.recommendation}</td></tr>"
            )
            if ml.top_features:
                h += (
                    "<tr><td colspan='2' style='padding-top:5px;"
                    "color:#8b949e;font-size:9px'>KEY FEATURES:</td></tr>"
                )
                for feat, val in list(ml.top_features.items())[:4]:
                    h += (
                        f"<tr><td style='color:#484f58;font-size:10px;padding-left:6px'>{feat}</td>"
                        f"<td style='color:#8b949e;font-size:10px'>{val:.4f}</td></tr>"
                    )
            h += "</table></div>"
            combined = (a.confidence_score + ml.ml_confidence) / 2
            cc = "#3fb950" if combined >= 65 else "#f0883e" if combined >= 45 else "#f85149"
            h += (
                f"<div style='margin-top:8px;padding:8px;background:#161b22;"
                f"border-radius:4px;border-left:3px solid {cc}'>"
                f"<span style='color:#8b949e;font-size:10px'>COMBINED: </span>"
                f"<span style='color:{cc};font-size:16px;font-weight:bold'>{combined:.1f}%</span>"
                f"</div>"
            )

        # ── MTF ALIGNMENT ─────────────────────────────────────────
        mtf_alignment   = getattr(a, "mtf_alignment",   "NEUTRAL")
        mtf_bias_5m     = getattr(a, "mtf_bias_5m",     "NEUTRAL")
        mtf_bias_15m    = getattr(a, "mtf_bias_15m",    "NEUTRAL")
        mtf_score_delta = getattr(a, "mtf_score_delta", 0.0)
        _mc = {
            "STRONG": "#3fb950", "PARTIAL": "#a8ff78",
            "NEUTRAL": "#8b949e", "WEAK": "#f0883e", "OPPOSING": "#f85149",
        }
        _arr = lambda b: "▲" if b == "BULLISH" else "▼" if b == "BEARISH" else "◆"
        _ds  = f"{mtf_score_delta:+.0f}%" if mtf_score_delta != 0 else "0%"
        mc   = _mc.get(mtf_alignment, "#8b949e")
        h += (
            f"<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
            f"margin:8px 0 3px'>MULTI-TIMEFRAME ALIGNMENT</div>"
            f"<div style='background:#1c2128;border:1px solid #30363d;"
            f"border-radius:4px;padding:8px;font-size:11px'>"
            f"<table style='width:100%;border-collapse:collapse'>"
            f"<tr><td style='color:#8b949e;padding:2px 0;width:110px'>5-min bias</td>"
            f"<td style='color:#c9d1d9'>{_arr(mtf_bias_5m)} {mtf_bias_5m}</td></tr>"
            f"<tr><td style='color:#8b949e;padding:2px 0'>15-min bias</td>"
            f"<td style='color:#c9d1d9'>{_arr(mtf_bias_15m)} {mtf_bias_15m}</td></tr>"
            f"<tr><td style='color:#8b949e;padding:2px 0'>Alignment</td>"
            f"<td style='color:{mc};font-weight:bold'>{mtf_alignment}</td></tr>"
            f"<tr><td style='color:#8b949e;padding:2px 0'>Score Δ</td>"
            f"<td style='color:{mc}'>{_ds}</td></tr>"
            f"</table></div>"
        )

        # ── OUTCOME TRACKING ──────────────────────────────────────
        if isinstance(a, TradeSignal) and getattr(a, "alert_id", 0):
            try:
                from database.manager import get_db
                from database.models import TradeOutcome
                with get_db().get_session() as session:
                    o = session.query(TradeOutcome).filter(
                        TradeOutcome.alert_id == a.alert_id
                    ).first()
                if o:
                    def _hit(hit, hit_time):
                        if hit:
                            t = hit_time.strftime("%H:%M:%S") if hit_time else "—"
                            return f"<span style='color:#3fb950'>✓ {t}</span>"
                        return "<span style='color:#484f58'>—</span>"

                    def _sf(v):
                        return f"{v:.0f}" if v else "—"

                    sc = (
                        "#3fb950" if o.outcome == "WIN"
                        else "#f85149" if o.outcome == "LOSS"
                        else "#8b949e"
                    )
                    h += (
                        f"<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
                        f"margin:8px 0 3px'>OUTCOME TRACKING</div>"
                        f"<div style='background:#0d1f0d;border:1px solid #238636;"
                        f"border-radius:4px;padding:10px;font-size:11px'>"
                        f"<table style='width:100%;border-collapse:collapse'>"
                        f"<tr><td style='color:#8b949e;padding:2px 0;width:80px'>Status</td>"
                        f"<td style='color:{sc};font-weight:bold'>{o.status}  {o.outcome or ''}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>Entry Spot</td>"
                        f"<td style='color:#c9d1d9'>{_sf(o.entry_spot)}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>SL ({_sf(o.spot_sl)})</td>"
                        f"<td>{_hit(o.sl_hit, o.sl_hit_time)}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>T1 ({_sf(o.spot_t1)})</td>"
                        f"<td>{_hit(o.t1_hit, o.t1_hit_time)}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>T2 ({_sf(o.spot_t2)})</td>"
                        f"<td>{_hit(o.t2_hit, o.t2_hit_time)}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>T3 ({_sf(o.spot_t3)})</td>"
                        f"<td>{_hit(o.t3_hit, o.t3_hit_time)}</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:4px 0 2px'>MFE</td>"
                        f"<td style='color:#3fb950'>{(o.mfe_atr or 0):.2f}× ATR</td></tr>"
                        f"<tr><td style='color:#8b949e;padding:2px 0'>MAE</td>"
                        f"<td style='color:#f85149'>{(o.mae_atr or 0):.2f}× ATR</td></tr>"
                        f"</table></div>"
                    )

                    # Post-close block (appears after EOD flush)
                    if o.post_close_eod_spot is not None:
                        rc2 = "#3fb950" if o.post_sl_reversal else "#484f58"
                        fc  = "#3fb950" if o.post_sl_full_recovery else "#484f58"
                        h += (
                            f"<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
                            f"margin:8px 0 3px'>POST-CLOSE TRACKING (full day)</div>"
                            f"<div style='background:#1c1508;border:1px solid #f0883e;"
                            f"border-radius:4px;padding:10px;font-size:11px'>"
                            f"<table style='width:100%;border-collapse:collapse'>"
                            f"<tr><td style='color:#8b949e;padding:2px 0;width:80px'>EOD Spot</td>"
                            f"<td style='color:#e6edf3;font-weight:bold'>{_sf(o.post_close_eod_spot)}</td></tr>"
                            f"<tr><td style='color:#8b949e;padding:2px 0'>T1 after close</td>"
                            f"<td>{_hit(o.post_close_t1_hit, o.post_close_t1_hit_time)}</td></tr>"
                            f"<tr><td style='color:#8b949e;padding:2px 0'>T2 after close</td>"
                            f"<td>{_hit(o.post_close_t2_hit, o.post_close_t2_hit_time)}</td></tr>"
                            f"<tr><td style='color:#8b949e;padding:2px 0'>T3 after close</td>"
                            f"<td>{_hit(o.post_close_t3_hit, o.post_close_t3_hit_time)}</td></tr>"
                            f"<tr><td style='color:#8b949e;padding:4px 0 2px'>Post MFE</td>"
                            f"<td style='color:#3fb950'>{(o.post_close_max_fav_atr or 0):.2f}× ATR</td></tr>"
                            f"<tr><td style='color:#8b949e;padding:2px 0'>Post MAE</td>"
                            f"<td style='color:#f85149'>{(o.post_close_max_adv_atr or 0):.2f}× ATR</td></tr>"
                        )
                        if o.sl_hit:
                            h += (
                                f"<tr><td colspan='2' style='padding-top:6px;"
                                f"border-top:1px solid #30363d'></td></tr>"
                                f"<tr><td style='color:#8b949e;padding:2px 0'>SL Reversal</td>"
                                f"<td style='color:{rc2};font-weight:bold'>"
                                f"{'YES — SL too tight' if o.post_sl_reversal else 'No'}</td></tr>"
                                f"<tr><td style='color:#8b949e;padding:2px 0'>Full Recovery</td>"
                                f"<td style='color:{fc};font-weight:bold'>"
                                f"{'YES — hit T3' if o.post_sl_full_recovery else 'No'}</td></tr>"
                            )
                        h += "</table></div>"
                    elif o.status == "CLOSED" and o.exit_reason != "EOD":
                        h += (
                            "<div style='color:#484f58;font-size:10px;"
                            "margin:6px 0;padding:6px;background:#161b22;"
                            "border-radius:3px'>Post-close monitoring active — "
                            "EOD data available at 15:30 IST</div>"
                        )
            except Exception:
                pass

        # ── SETUPS FIRED ──────────────────────────────────────────
        alert_id = getattr(a, "alert_id", 0)
        if alert_id:
            try:
                setups = get_db().get_setups_for_alert(alert_id)
                if setups:
                    _grade_color = {
                        "A++": "#ffd700", "A+": "#3fb950", "A": "#3fb950",
                        "A-": "#a8ff78", "B": "#f0883e", "C-": "#8b949e", "D": "#484f58",
                    }
                    h += (
                        "<div style='color:#8b949e;font-size:9px;letter-spacing:.5px;"
                        "margin:8px 0 3px'>SETUPS FIRED</div>"
                        "<div style='background:#1c1508;border:1px solid #30363d;"
                        "border-radius:4px;padding:8px;font-size:11px'>"
                        "<table style='width:100%;border-collapse:collapse'>"
                    )
                    for s in setups:
                        gc = _grade_color.get(s["setup_grade"], "#8b949e")
                        lbl_text = ""
                        if s["label"] == 1:
                            q = s["label_quality"]
                            lbl_text = (
                                " <span style='color:#3fb950'>T3✓</span>" if q >= 3
                                else " <span style='color:#3fb950'>T2✓</span>" if q >= 2
                                else " <span style='color:#a8ff78'>T1✓</span>"
                            )
                        elif s["label"] == 0:
                            lbl_text = " <span style='color:#f85149'>SL✗</span>"
                        h += (
                            f"<tr>"
                            f"<td style='padding:2px 0;width:30px'>"
                            f"<span style='color:{gc};font-weight:bold;font-size:10px'>"
                            f"{s['setup_grade']}</span></td>"
                            f"<td style='color:#c9d1d9;padding:2px 4px'>{s['setup_name']}"
                            f"{lbl_text}</td>"
                            f"<td style='color:#8b949e;text-align:right;font-size:10px'>"
                            f"exp {s['expected_wr']:.0f}%</td>"
                            f"</tr>"
                        )
                    h += "</table></div>"
            except Exception:
                pass

        h += "</div>"
        self._body.setHtml(h)

    def clear(self):
        self._body.setHtml(self._EMPTY_HTML)


# ─────────────────────────────────────────────────────────────────
# ALERTS TAB
# ─────────────────────────────────────────────────────────────────
class AlertsTab(QWidget):

    def __init__(self):
        super().__init__()
        self._db = get_db()
        self._row_alerts: dict = {}
        self._last_confirmed = None   # holds last CONFIRMED alert_obj for panel lock
        self._build_ui()
        t = QTimer(self)
        t.timeout.connect(self._ml_panel.refresh)
        t.start(10000)
        self._ml_panel.refresh()

    def _build_ui(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(8)

        # ── ML status bar ─────────────────────────────────────────
        self._ml_panel = MLStatusPanel()
        ly.addWidget(self._ml_panel)

        # ── Alert table header ────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("TRADE ALERTS — REAL-TIME", "#58a6ff", bold=True, size=13))
        hdr.addWidget(_lbl("   S=Strategy  M=ML  C=Combined", "#484f58", size=10))
        hdr.addStretch()
        btn = QPushButton("Clear")
        btn.setStyleSheet(
            "background:#21262d;color:#8b949e;border:1px solid #30363d;"
            "border-radius:4px;padding:4px 10px;"
        )
        btn.clicked.connect(self._clear)
        hdr.addWidget(btn)
        ly.addLayout(hdr)

        # ── Main splitter: table | right panels ───────────────────
        main_split = QSplitter(Qt.Horizontal)

        # Left — alert table
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "TIME", "INDEX", "TYPE", "DIR",
            "S%", "M%", "C%", "ENGINES",
            "INSTRUMENT", "SPOT", "OUTCOME",
        ])
        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(QHeaderView.Stretch)
        for i in (0, 4, 5, 6, 7, 10):
            hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_select)
        self._table.setStyleSheet(
            "QTableWidget { background:#0d1117; color:#c9d1d9; "
            "gridline-color:#21262d; border:1px solid #30363d; }"
            "QHeaderView::section { background:#161b22; color:#8b949e; "
            "border:none; padding:4px; font-size:10px; }"
        )
        main_split.addWidget(self._table)

        # Right — vertical splitter: alert card (top) + details (bottom)
        right_split = QSplitter(Qt.Vertical)

        self._alert_panel = TradeAlertPanel()
        self._alert_panel.setMinimumHeight(200)
        right_split.addWidget(self._alert_panel)

        self._detail_panel = TradeDetailPanel()
        self._detail_panel.setMinimumHeight(200)
        right_split.addWidget(self._detail_panel)

        right_split.setSizes([280, 420])

        # Wrap right splitter in a plain widget so main_split sizes work
        right_wrap = QWidget()
        rw_ly = QVBoxLayout(right_wrap)
        rw_ly.setContentsMargins(0, 0, 0, 0)
        rw_ly.setSpacing(0)
        rw_ly.addWidget(right_split)

        main_split.addWidget(right_wrap)
        main_split.setSizes([800, 400])
        ly.addWidget(main_split)

        # ── Stats bar ─────────────────────────────────────────────
        sb_frame = QFrame()
        sb_frame.setStyleSheet(
            "background:#161b22; border:1px solid #30363d; border-radius:3px;"
        )
        sb = QHBoxLayout(sb_frame)
        sb.setContentsMargins(12, 6, 12, 6)
        self._today   = self._stat(sb, "TODAY")
        self._total   = self._stat(sb, "SIGNALS")
        self._winrate = self._stat(sb, "WIN RATE")
        self._t1_rate = self._stat(sb, "T1 RATE")
        self._t2_rate = self._stat(sb, "T2 RATE")
        self._t3_rate = self._stat(sb, "T3 RATE")
        self._sl_rate = self._stat(sb, "SL RATE")
        self._ml_acc  = self._stat(sb, "SIGNAL WIN %")
        sb.addStretch()
        ly.addWidget(sb_frame)
        self._update_stats()

    # ── helpers ───────────────────────────────────────────────────

    def _stat(self, parent, label):
        f = QFrame()
        l = QVBoxLayout(f)
        l.setContentsMargins(8, 0, 16, 0); l.setSpacing(1)
        l.addWidget(_lbl(label, "#8b949e", size=9))
        v = _lbl("—", "#e6edf3", bold=True, size=13)
        l.addWidget(v)
        parent.addWidget(f)
        return v

    # ── public API ────────────────────────────────────────────────

    def add_alert(self, alert_obj):
        from engines.signal_aggregator import TradeSignal
        r = 0
        self._table.insertRow(r)
        self._row_alerts = {k + 1: v for k, v in self._row_alerts.items()}
        self._row_alerts[0] = alert_obj

        is_confirmed = getattr(alert_obj, "is_confirmed", False)
        is_trade     = isinstance(alert_obj, TradeSignal)
        dc  = "#3fb950" if alert_obj.direction == "BULLISH" else "#f85149"
        ml  = getattr(alert_obj, "ml_prediction", None)
        ml_ok  = ml is not None and ml.is_available
        ml_pct = ml.ml_confidence if ml_ok else 0.0
        s_pct  = alert_obj.confidence_score
        c_pct  = (s_pct + ml_pct) / 2 if ml_ok else s_pct
        cc     = "#3fb950" if c_pct >= 65 else "#f0883e" if c_pct >= 45 else "#8b949e"

        engines_list = getattr(alert_obj, "engines_triggered", [])
        eng_count = len(engines_list) if engines_list else 0
        eng_text  = f"{eng_count}/7" if eng_count > 0 else "--"
        eng_color = "#3fb950" if eng_count >= 5 else "#f0883e" if eng_count >= 3 else "#8b949e"

        # ── TYPE cell — confirmed gets a special golden badge ─────
        if is_confirmed:
            type_text  = "✅ CONFIRMED"
            type_color = "#ffd700"
            type_bg    = "#1a1a00"
        elif is_trade:
            type_text  = "🎯 TRADE"
            type_color = "#f85149"
            type_bg    = "#2d1414"
        else:
            type_text  = "⚡ EARLY"
            type_color = "#f0883e"
            type_bg    = "#2d1c08"

        self._table.setItem(r, 0, _item(alert_obj.timestamp.strftime("%H:%M:%S"), "#8b949e"))
        self._table.setItem(r, 1, _item(alert_obj.index_name, "#58a6ff", bold=True))
        self._table.setItem(r, 2, _item(type_text, type_color, bold=True, bg=type_bg))
        self._table.setItem(r, 3, _item(alert_obj.direction, dc, bold=True))
        self._table.setItem(r, 4, _item(f"{s_pct:.0f}%", "#c9d1d9"))
        self._table.setItem(r, 5, _item(
            f"{ml_pct:.0f}%" if ml_ok else "—",
            "#58a6ff" if ml_ok else "#484f58", bold=ml_ok,
        ))
        self._table.setItem(r, 6, _item(f"{c_pct:.0f}%", cc, bold=True))
        self._table.setItem(r, 7, _item(eng_text, eng_color, bold=True))
        self._table.setItem(r, 8, _item(getattr(alert_obj, "suggested_instrument", "—"), "#c9d1d9"))
        self._table.setItem(r, 9, _item(f"{alert_obj.spot_price:.2f}", "#e6edf3"))
        # OUTCOME column
        if is_confirmed or is_trade:
            self._table.setItem(r, 10, _item("OPEN", "#484f58"))
        else:
            self._table.setItem(r, 10, _item("—", "#30363d"))

        # Confirmed rows are taller so they stand out
        self._table.setRowHeight(r, 36 if is_confirmed else 30)

        # Auto-select newest row in table
        self._table.selectRow(0)

        # Panel update logic:
        # - CONFIRMED alert → always show it and lock the panels on it
        # - Any other alert → only update panels if no confirmed trade is locked
        if is_confirmed:
            self._last_confirmed = alert_obj
            self._alert_panel.show_alert(alert_obj)
            self._detail_panel.show_alert(alert_obj)
        elif self._last_confirmed is None:
            self._alert_panel.show_alert(alert_obj)
            self._detail_panel.show_alert(alert_obj)

        if self._table.rowCount() > 250:
            self._table.removeRow(250)
            self._row_alerts.pop(250, None)
        self._update_stats()

    def refresh_outcome(self, outcome_id: int, outcome_str: str = ""):
        """
        Called (via Qt signal) when OutcomeTracker closes a trade.
        Updates OUTCOME column in table and refreshes the stats bar.
        """
        try:
            with self._db.get_session() as session:
                from database.models import TradeOutcome
                outcome = session.query(TradeOutcome).filter(
                    TradeOutcome.id == outcome_id
                ).first()
                if not outcome:
                    return
                badge, color = self._outcome_badge(outcome)
                aid = outcome.alert_id

            for row_idx, alert_obj in self._row_alerts.items():
                if getattr(alert_obj, "alert_id", None) == aid:
                    self._table.setItem(row_idx, 10, _item(badge, color, bold=True))
                    break

            self._update_stats()
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"refresh_outcome error: {e}")

    @staticmethod
    def _outcome_badge(outcome) -> tuple:
        if getattr(outcome, "status", "OPEN") == "OPEN":
            if getattr(outcome, "t2_hit", False):
                return "T2✓ OPEN", "#a8ff78"
            if getattr(outcome, "t1_hit", False):
                return "T1✓ OPEN", "#3fb950"
            return "OPEN", "#484f58"
        if getattr(outcome, "t3_hit", False):
            return "T3✓ WIN",  "#3fb950"
        if getattr(outcome, "t2_hit", False):
            return "T2✓ WIN",  "#3fb950"
        if getattr(outcome, "t1_hit", False):
            return "T1✓",      "#a8ff78"
        if getattr(outcome, "sl_hit", False):
            return "SL✗ LOSS", "#f85149"
        return "EOD",           "#8b949e"

    # ── internal slots ────────────────────────────────────────────

    def _on_select(self):
        a = self._row_alerts.get(self._table.currentRow())
        if a:
            self._alert_panel.show_alert(a)
            self._detail_panel.show_alert(a)

    def _clear(self):
        self._table.setRowCount(0)
        self._row_alerts.clear()
        self._alert_panel.clear()
        self._detail_panel.clear()

    def _update_stats(self):
        s = self._db.get_alert_stats()
        self._today.setText(str(s["today"]))
        self._total.setText(str(s["total"]))
        wr = s["win_rate"]
        wc = "#3fb950" if wr >= 60 else "#f0883e" if wr >= 40 else "#f85149"
        self._winrate.setText(f"{wr:.1f}%")
        self._winrate.setStyleSheet(f"color:{wc};font-size:13px;font-weight:bold;")

        try:
            os_ = self._db.get_outcome_stats()

            def _pc(v, good=50):
                return "#3fb950" if v >= good else "#f0883e" if v >= 25 else "#8b949e"

            self._t1_rate.setText(f"{os_['t1_rate']:.0f}%")
            self._t1_rate.setStyleSheet(f"color:{_pc(os_['t1_rate'])};font-size:13px;font-weight:bold;")
            self._t2_rate.setText(f"{os_['t2_rate']:.0f}%")
            self._t2_rate.setStyleSheet(f"color:{_pc(os_['t2_rate'],35)};font-size:13px;font-weight:bold;")
            self._t3_rate.setText(f"{os_['t3_rate']:.0f}%")
            self._t3_rate.setStyleSheet(f"color:{_pc(os_['t3_rate'],20)};font-size:13px;font-weight:bold;")
            sl_r = os_["sl_rate"]
            sc = "#f85149" if sl_r >= 50 else "#f0883e" if sl_r >= 30 else "#3fb950"
            self._sl_rate.setText(f"{sl_r:.0f}%")
            self._sl_rate.setStyleSheet(f"color:{sc};font-size:13px;font-weight:bold;")
        except Exception:
            pass

        try:
            # B9 fix: was AutoLabeler() which creates a new DB connection every 10 s.
            # Query label stats directly via the shared DatabaseManager instead.
            with self._db.get_session() as _s:
                from database.models import MLFeatureRecord
                total   = _s.query(MLFeatureRecord).count()
                labeled = _s.query(MLFeatureRecord).filter(MLFeatureRecord.label != -1).count()
                pos     = _s.query(MLFeatureRecord).filter(MLFeatureRecord.label == 1).count()
            acc = round(pos / max(labeled, 1) * 100, 1)
            ac  = "#3fb950" if acc >= 60 else "#f0883e" if acc >= 40 else "#8b949e"
            self._ml_acc.setText(f"{acc:.1f}%")
            self._ml_acc.setStyleSheet(f"color:{ac};font-size:13px;font-weight:bold;")
        except Exception:
            pass
