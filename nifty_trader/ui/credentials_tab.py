"""
ui/credentials_tab.py
─────────────────────────────────────────────────────────────────
Tab 0 — Credentials & Connection

Fyers auth flow implemented exactly:
  Field 1: Client ID     (e.g. XB12345)
  Field 2: App ID        (e.g. XB12345-100)
  Field 3: Secret Key    (app secret)
  ─────────────────────────────────────────
  [Generate Token]  → opens Fyers login in browser
  [Copy URL]        → copies login URL to clipboard
  ─────────────────────────────────────────
  Auth Token field  ← user pastes token from redirect URL
  [Save Auth Token] → validates + saves token + checks expiry
  ─────────────────────────────────────────
  Token status: "Expires 17 Mar 14:59 IST  (8h 22m left)"
                "TOKEN EXPIRED — generate a new one"

Token persistence:
  • Saved to auth/fyers_token.json with expires_at (midnight IST)
  • On next launch: auto-loads if valid, silently connects
  • On expiry: credential tab shows expired badge, prompts new token
  • All other fields saved to auth/credentials.json (base64 obfuscated)
"""

import json
import logging
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QFrame, QGroupBox, QScrollArea, QTextEdit,
    QCheckBox, QMessageBox, QSizePolicy, QSplitter
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot
from PySide6.QtGui import QGuiApplication

import config
from data.adapters import is_broker_active

logger = logging.getLogger(__name__)

AUTH_DIR   = Path("auth")
CREDS_FILE = AUTH_DIR / "credentials.json"


# ──────────────────────────────────────────────────────────────────
# Thread-safe signals
# ──────────────────────────────────────────────────────────────────
class ConnBridge(QObject):
    status_changed = Signal(bool, str)
    auth_url_ready = Signal(str)
    log_msg        = Signal(str, str)   # (message, color)


# ──────────────────────────────────────────────────────────────────
# Secure credential storage via OS keyring
# Falls back to base64 obfuscation if keyring is unavailable
# (e.g. headless CI environments with no secret service).
# ──────────────────────────────────────────────────────────────────
_KEYRING_SERVICE = "NiftyTrader"

try:
    import keyring as _keyring
    _KEYRING_OK = True
except ImportError:
    _KEYRING_OK = False
    logger = logging.getLogger(__name__)
    logging.getLogger(__name__).warning(
        "keyring not installed — credentials stored as base64 (run: pip install keyring)"
    )

def _save_secret(key: str, value: str):
    """Store a credential securely in the OS keyring."""
    if not value:
        _delete_secret(key)
        return
    if _KEYRING_OK:
        _keyring.set_password(_KEYRING_SERVICE, key, value)
    else:
        import base64
        # base64 fallback — not secure, just obfuscated
        _FALLBACK_STORE[key] = base64.b64encode(value.encode()).decode()

def _load_secret(key: str) -> str:
    """Retrieve a credential from the OS keyring."""
    if _KEYRING_OK:
        return _keyring.get_password(_KEYRING_SERVICE, key) or ""
    else:
        import base64
        v = _FALLBACK_STORE.get(key, "")
        try:
            return base64.b64decode(v.encode()).decode() if v else ""
        except Exception:
            return v

def _delete_secret(key: str):
    """Remove a credential from the OS keyring (best-effort)."""
    if _KEYRING_OK:
        try:
            _keyring.delete_password(_KEYRING_SERVICE, key)
        except Exception:
            pass
    else:
        _FALLBACK_STORE.pop(key, None)

_FALLBACK_STORE: dict = {}   # used only when keyring is unavailable

def _lbl(text, color="#8b949e", bold=False, size=11):
    w = QLabel(text)
    w.setStyleSheet(f"color:{color};font-size:{size}px;" + ("font-weight:bold;" if bold else ""))
    return w

def _inp(placeholder="", pw=False):
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    if pw: w.setEchoMode(QLineEdit.Password)
    w.setStyleSheet("""
        QLineEdit{background:#0d1117;color:#e6edf3;border:1px solid #30363d;
            border-radius:4px;padding:6px 10px;font-size:12px;font-family:Consolas,monospace;}
        QLineEdit:focus{border-color:#58a6ff;}
        QLineEdit:read-only{color:#8b949e;background:#161b22;}
    """)
    return w

def _btn(text, color="#21262d", tc="#c9d1d9", bold=False):
    b = QPushButton(text)
    b.setStyleSheet(f"""
        QPushButton{{background:{color};color:{tc};border:1px solid #30363d;
            border-radius:4px;padding:7px 16px;font-size:12px;
            {'font-weight:bold;' if bold else ''}font-family:Consolas,monospace;}}
        QPushButton:hover{{background:#30363d;border-color:#58a6ff;}}
        QPushButton:pressed{{background:#1f6feb;}}
        QPushButton:disabled{{color:#484f58;border-color:#21262d;}}
    """)
    return b

def _grp(title):
    g = QGroupBox(title)
    g.setStyleSheet("""
        QGroupBox{color:#8b949e;border:1px solid #30363d;border-radius:5px;
            margin-top:10px;padding-top:6px;font-size:10px;letter-spacing:1px;}
        QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}
    """)
    return g


# ──────────────────────────────────────────────────────────────────
# CREDENTIALS TAB
# ──────────────────────────────────────────────────────────────────
class CredentialsTab(QWidget):

    connection_changed = Signal(bool, str)

    BROKERS = {
        "fyers":  "Fyers  (OAuth2)",
        "mock":   "Mock / Simulation",
        "dhan":   "Dhan HQ  — sleeping",
        "kite":   "Zerodha Kite  — sleeping",
        "upstox": "Upstox  — sleeping",
    }

    def __init__(self, data_manager):
        super().__init__()
        self._dm      = data_manager
        self._bridge  = ConnBridge()
        self._broker  = config.BROKER
        self._fyers_adapter = None
        self._login_url     = ""
        self._connecting    = False
        self._spinner_i     = 0
        self._fields: Dict[str, QLineEdit] = {}

        self._bridge.status_changed.connect(self._on_status)
        self._bridge.auth_url_ready.connect(self._on_url_ready)
        self._bridge.log_msg.connect(self._log)

        # Debounced auto-save: fires 1.5 s after the last field edit
        self._auto_save_timer = QTimer()
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1500)
        self._auto_save_timer.timeout.connect(self._auto_save)

        self._build_ui()
        self._load_saved_credentials()
        self._rebuild_fields(self._broker)

    # ─── UI Construction ─────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("BROKER CREDENTIALS & CONNECTION", "#58a6ff", True, 14))
        hdr.addStretch()
        self._status_badge = QLabel("● DISCONNECTED")
        self._status_badge.setStyleSheet("color:#f85149;font-weight:bold;font-size:12px;")
        hdr.addWidget(self._status_badge)
        outer.addLayout(hdr)

        splitter = QSplitter(Qt.Horizontal)

        # ── LEFT (scrollable) ─────────────────────────────────────
        left_inner = QWidget()
        ll = QVBoxLayout(left_inner)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(10)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:#161b22;width:6px;border-radius:3px;}"
            "QScrollBar::handle:vertical{background:#30363d;border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        left_scroll.setWidget(left_inner)
        left = left_scroll

        # Broker selector
        bg = _grp("BROKER SELECTION")
        bl = QVBoxLayout(bg)
        bl.setSpacing(6)
        bl.addWidget(_lbl("Select your broker:"))
        self._broker_combo = QComboBox()
        self._broker_combo.setStyleSheet("""
            QComboBox{background:#161b22;color:#c9d1d9;border:1px solid #30363d;
                border-radius:4px;padding:6px 10px;font-size:13px;}
            QComboBox::drop-down{border:none;width:24px;}
            QComboBox QAbstractItemView{background:#161b22;color:#c9d1d9;
                border:1px solid #30363d;selection-background-color:#1f6feb;}
        """)
        for k, v in self.BROKERS.items():
            self._broker_combo.addItem(v, userData=k)
        idx = list(self.BROKERS.keys()).index(config.BROKER) if config.BROKER in self.BROKERS else 0
        self._broker_combo.setCurrentIndex(idx)
        self._broker_combo.currentIndexChanged.connect(self._on_broker_changed)
        bl.addWidget(self._broker_combo)
        ll.addWidget(bg)

        # Dynamic credential fields
        self._cred_grp = _grp("CREDENTIALS")
        self._cred_layout = QGridLayout()
        self._cred_layout.setSpacing(8)
        self._cred_layout.setColumnStretch(1, 1)
        self._cred_grp.setLayout(self._cred_layout)
        ll.addWidget(self._cred_grp)

        # Fyers OAuth block
        self._fyers_grp = _grp("TOKEN GENERATION  (Fyers OAuth2)")
        fl = QVBoxLayout(self._fyers_grp)
        fl.setSpacing(8)

        fl.addWidget(_lbl("Step 1 — Click 'Generate Token' to open Fyers login page:",
                           "#8b949e", size=10))
        row1 = QHBoxLayout()
        self._gen_btn  = _btn("🔑  Generate Token", "#1f6feb", "#fff", True)
        self._gen_btn.clicked.connect(self._fyers_generate)
        self._copy_btn = _btn("📋  Copy URL")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_url)
        row1.addWidget(self._gen_btn)
        row1.addWidget(self._copy_btn)
        row1.addStretch()
        fl.addLayout(row1)

        self._url_display = QLineEdit()
        self._url_display.setReadOnly(True)
        self._url_display.setPlaceholderText("Login URL appears here after clicking Generate Token…")
        self._url_display.setStyleSheet(
            "QLineEdit{background:#161b22;color:#8b949e;border:1px solid #30363d;"
            "border-radius:4px;padding:5px 8px;font-size:10px;font-family:monospace;}"
        )
        fl.addWidget(self._url_display)

        fl.addWidget(_lbl(
            "Step 2 — After login, Fyers redirects to:\n"
            "  https://trade.fyers.in/api-login/redirect-uri/index.html?auth_code=XXXX…\n"
            "  Copy the auth_code value and paste it below:",
            "#8b949e", size=10
        ))
        self._token_input = _inp("Paste auth_code here  (e.g. eyJhbGci…)")
        fl.addWidget(self._token_input)

        # Token status badge
        self._token_status = QLabel("No token saved")
        self._token_status.setStyleSheet(
            "color:#484f58;font-size:11px;font-weight:bold;padding:4px 0;"
        )
        fl.addWidget(self._token_status)

        row2 = QHBoxLayout()
        self._save_token_btn = _btn("✅  Save Auth Token", "#238636", "#fff", True)
        self._save_token_btn.clicked.connect(self._fyers_save_token)
        self._regen_btn = _btn("↻  Token Expired — Generate New")
        self._regen_btn.setVisible(False)
        self._regen_btn.clicked.connect(self._fyers_generate)
        row2.addWidget(self._save_token_btn)
        row2.addWidget(self._regen_btn)
        row2.addStretch()
        fl.addLayout(row2)

        self._fyers_grp.setVisible(False)
        ll.addWidget(self._fyers_grp)

        # Connect / Disconnect buttons
        btns = QHBoxLayout()
        self._connect_btn    = _btn("⚡  CONNECT", "#1f6feb", "#fff", True)
        self._connect_btn.setFixedHeight(38)
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn = _btn("✕  Disconnect")
        self._disconnect_btn.setFixedHeight(38)
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._save_creds_btn = _btn("💾  Save Credentials")
        self._save_creds_btn.clicked.connect(self._save_all)
        btns.addWidget(self._connect_btn)
        btns.addWidget(self._disconnect_btn)
        btns.addStretch()
        btns.addWidget(self._save_creds_btn)
        ll.addLayout(btns)

        # Telegram
        tg = _grp("TELEGRAM ALERTS  (Optional)")
        tgl = QGridLayout(tg)
        tgl.setSpacing(8); tgl.setColumnStretch(1, 1)
        self._tg_enabled = QCheckBox("Enable Telegram alerts")
        self._tg_enabled.setStyleSheet("color:#c9d1d9;font-size:12px;")
        self._tg_enabled.setChecked(config.TELEGRAM_ENABLED)
        tgl.addWidget(self._tg_enabled, 0, 0, 1, 2)
        tgl.addWidget(_lbl("Bot Token:"), 1, 0)
        self._tg_token = _inp("123456:ABCdef…", pw=True)
        self._tg_token.setText(config.TELEGRAM_BOT_TOKEN)
        tgl.addWidget(self._tg_token, 1, 1)
        tgl.addWidget(_lbl("Chat ID:"), 2, 0)
        self._tg_chat = _inp("-1001234567890")
        self._tg_chat.setText(config.TELEGRAM_CHAT_ID)
        tgl.addWidget(self._tg_chat, 2, 1)
        tg_test = _btn("📨  Test Telegram")
        tg_test.clicked.connect(self._test_tg)
        tgl.addWidget(tg_test, 3, 0, 1, 2)
        ll.addWidget(tg)
        ll.addStretch()

        # ── RIGHT ────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(8)

        # Status card
        sc = _grp("CONNECTION STATUS")
        scl = QGridLayout(sc); scl.setSpacing(6)
        def _sr(g, row, k):
            g.addWidget(_lbl(k), row, 0)
            v = QLabel("—"); v.setStyleSheet("color:#e6edf3;font-size:12px;font-weight:bold;")
            g.addWidget(v, row, 1); return v
        self._cc_broker   = _sr(scl, 0, "Broker:")
        self._cc_status   = _sr(scl, 1, "Status:")
        self._cc_conntime = _sr(scl, 2, "Connected at:")
        self._cc_mode     = _sr(scl, 3, "Data mode:")
        self._cc_expiry   = _sr(scl, 4, "Token expiry:")
        rl.addWidget(sc)

        rl.addWidget(_lbl("CONNECTION LOG", "#8b949e", size=10))
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setStyleSheet(
            "QTextEdit{background:#0d1117;color:#3fb950;border:1px solid #30363d;"
            "border-radius:4px;font-family:Consolas,monospace;font-size:11px;}"
        )
        rl.addWidget(self._log_box)

        # Guide
        self._guide_grp = _grp("QUICK GUIDE")
        gl = QVBoxLayout(self._guide_grp)
        self._guide_lbl = QLabel()
        self._guide_lbl.setWordWrap(True)
        self._guide_lbl.setStyleSheet("color:#8b949e;font-size:11px;line-height:1.7;")
        gl.addWidget(self._guide_lbl)
        rl.addWidget(self._guide_grp)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([560, 440])
        outer.addWidget(splitter)

        # Spinner
        self._spinner_lbl = QLabel("")
        self._spinner_lbl.setStyleSheet("color:#f0883e;font-size:11px;")
        self._spinner_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._spinner_lbl)
        self._spin_timer = QTimer(); self._spin_timer.timeout.connect(self._tick_spin)
        self._spin_frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

        # Token expiry refresh
        self._expiry_timer = QTimer()
        self._expiry_timer.timeout.connect(self._refresh_token_display)
        self._expiry_timer.start(30_000)  # every 30s

    # ─── Dynamic fields ───────────────────────────────────────────
    def _rebuild_fields(self, broker: str):
        while self._cred_layout.count():
            item = self._cred_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._fields.clear()

        sleeping = not is_broker_active(broker)

        if sleeping:
            notice = QLabel(
                f"  {broker.upper()} is not yet active in this build.\n"
                "  Only Fyers is wired for live trading right now.\n"
                "  The code is preserved and will be activated in a future release."
            )
            notice.setStyleSheet(
                "color:#f0883e;background:#1a1200;border:1px solid #f0883e;"
                "border-radius:4px;padding:10px;font-size:11px;line-height:1.6;"
            )
            notice.setWordWrap(True)
            self._cred_layout.addWidget(notice, 0, 0, 1, 2)
        else:
            creds = config.BROKER_CREDENTIALS.get(broker, {})
            defs  = self._field_defs(broker)
            for row, (key, label, pw) in enumerate(defs):
                self._cred_layout.addWidget(_lbl(f"{label}:"), row, 0)
                inp = _inp(f"Enter {label.lower()}", pw=pw)
                inp.setText(creds.get(key, ""))
                inp.textChanged.connect(self._schedule_auto_save)
                self._cred_layout.addWidget(inp, row, 1)
                self._fields[key] = inp

        self._connect_btn.setEnabled(not sleeping and not self._connecting)
        self._fyers_grp.setVisible(broker == "fyers")
        if broker == "fyers":
            self._refresh_token_display()
        self._guide_lbl.setText(self._guide_text(broker))

    def _field_defs(self, broker):
        return {
            "fyers": [
                ("client_id",  "Client ID",  False),
                ("app_id",     "App ID",     False),
                ("secret_key", "Secret Key", True),
            ],
            "dhan":  [
                ("client_id",    "Client ID",    False),
                ("access_token", "Access Token", True),
            ],
            "kite":  [
                ("api_key",      "API Key",      False),
                ("api_secret",   "API Secret",   True),
                ("access_token", "Access Token", True),
            ],
            "upstox": [
                ("api_key",      "API Key",      False),
                ("api_secret",   "API Secret",   True),
                ("redirect_uri", "Redirect URI", False),
                ("access_token", "Access Token", True),
            ],
            "mock":  [],
        }.get(broker, [])

    def _guide_text(self, broker):
        return {
            "fyers": (
                "1. Create an app at fyers.in → API → Create App\n"
                "2. Set redirect URI to:\n"
                "   https://trade.fyers.in/api-login/redirect-uri/index.html\n"
                "3. Enter Client ID, App ID, Secret Key above\n"
                "4. Click 'Generate Token' → log in → copy auth_code from URL\n"
                "5. Paste auth_code → click 'Save Auth Token'\n"
                "6. Token auto-reloads next launch until midnight IST"
            ),
            "dhan": (
                "1. Log in at dhanhq.co → My Profile → API Access\n"
                "2. Generate access token from Dhan console\n"
                "3. Enter Client ID + Access Token above → Connect"
            ),
            "kite": (
                "1. Log in at kite.zerodha.com → My Account → API Keys\n"
                "2. Create app → note API Key and API Secret\n"
                "3. Enter API Key + API Secret above → Save Credentials\n"
                "4. Either:\n"
                "   a) Generate today's access token via Kite console and paste it, OR\n"
                "   b) Paste token directly into Access Token field → Connect\n"
                "5. Token expires at 6:00 AM IST each day"
            ),
            "upstox": (
                "1. Log in at upstox.com → My Account → API & Integrations\n"
                "2. Create an app → note API Key and API Secret\n"
                "3. Set Redirect URI (default: http://localhost:8888/callback)\n"
                "4. Enter API Key, API Secret, and Redirect URI above → Save\n"
                "5. Either:\n"
                "   a) Click Connect → complete OAuth in browser → paste access token, OR\n"
                "   b) Paste an existing token directly into Access Token field → Connect\n"
                "6. Token expires at 3:30 AM IST each day"
            ),
            "mock": (
                "Mock mode — no broker needed.\n"
                "Generates realistic NIFTY / BANKNIFTY / MIDCPNIFTY\n"
                "with compression phases, option chains, and volume spikes.\n"
                "Use this to develop/test strategy logic before going live."
            ),
        }.get(broker, "")

    # ─── Broker changed ───────────────────────────────────────────
    def _on_broker_changed(self, idx):
        self._broker = self._broker_combo.itemData(idx)
        self._rebuild_fields(self._broker)
        self._log_msg(f"Broker → {self._broker}")
        # Save broker selection immediately so next launch restores it
        self._persist()

    # ─── Fyers token flow ─────────────────────────────────────────
    def _fyers_generate(self):
        self._apply_fields("fyers")
        c = config.BROKER_CREDENTIALS["fyers"]
        if not c.get("app_id") or not c.get("secret_key"):
            QMessageBox.warning(self, "Missing",
                                "Enter Client ID, App ID and Secret Key first.")
            return
        self._log_msg("Generating Fyers login URL…")
        def _t():
            try:
                from data.adapters.fyers_adapter import FyersAdapter
                self._fyers_adapter = FyersAdapter()
                url = self._fyers_adapter.generate_auth_url()
                self._bridge.auth_url_ready.emit(url)
            except ImportError:
                self._bridge.log_msg.emit(
                    "fyers-apiv3 not installed. Run: pip install fyers-apiv3", "#f0883e"
                )
            except Exception as e:
                self._bridge.log_msg.emit(f"URL error: {e}", "#f85149")
        threading.Thread(target=_t, daemon=True).start()

    def _fyers_save_token(self):
        token = self._token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "No Token", "Paste the auth_code first.")
            return
        # Strip common URL params if user pasted full URL
        if "auth_code=" in token:
            token = token.split("auth_code=")[-1].split("&")[0]
        self._log_msg(f"Saving auth token ({token[:8]}…)")
        self._set_connecting(True)
        def _t():
            try:
                self._apply_fields("fyers")
                if self._fyers_adapter is None:
                    from data.adapters.fyers_adapter import FyersAdapter
                    self._fyers_adapter = FyersAdapter()
                ok = self._fyers_adapter.exchange_auth_code(token)
                if ok:
                    config.BROKER = "fyers"
                    connected = self._dm.reconnect("fyers")
                    self._bridge.status_changed.emit(
                        connected,
                        "Fyers connected ✓" if connected else "Token saved but data connect failed"
                    )
                else:
                    self._bridge.status_changed.emit(False, "Auth code exchange failed")
            except Exception as e:
                self._bridge.status_changed.emit(False, str(e))
        threading.Thread(target=_t, daemon=True).start()

    def _refresh_token_display(self):
        """Update token expiry status label."""
        if self._broker != "fyers":
            return
        try:
            from data.adapters.fyers_adapter import fyers_token_expiry_display, load_fyers_token
            cached = load_fyers_token()
            if cached:
                txt   = fyers_token_expiry_display()
                color = "#3fb950"
                self._token_status.setText(f"✓ {txt}")
                self._token_status.setStyleSheet(f"color:{color};font-size:11px;font-weight:bold;")
                self._regen_btn.setVisible(False)
                self._cc_expiry.setText(txt)
            else:
                self._token_status.setText("⚠  TOKEN EXPIRED — generate a new one")
                self._token_status.setStyleSheet("color:#f85149;font-size:11px;font-weight:bold;")
                self._regen_btn.setVisible(True)
                self._cc_expiry.setText("Expired")
                self._cc_expiry.setStyleSheet("color:#f85149;font-weight:bold;")
        except Exception:
            pass

    # ─── Connect / Disconnect ─────────────────────────────────────
    def _connect(self):
        if self._connecting: return
        broker = self._broker
        if not is_broker_active(broker):
            self._log_msg(f"{broker.upper()} is sleeping — connection not available", "#f0883e")
            return
        self._apply_fields(broker)
        if broker == "mock":
            self._do_connect(broker); return
        missing = [k for k, w in self._fields.items() if not w.text().strip()
                   and k not in ("app_id",)]  # app_id has fallback
        if missing and broker != "fyers":
            QMessageBox.warning(self, "Missing", f"Please fill: {', '.join(missing)}")
            return
        self._do_connect(broker)

    def _do_connect(self, broker):
        self._set_connecting(True)
        self._log_msg(f"Connecting to {broker}…")
        config.BROKER = broker
        def _t():
            try:
                ok = self._dm.reconnect(broker)
                msg = f"Connected to {broker}" if ok else f"Failed — {broker}"
                self._bridge.status_changed.emit(ok, msg)
            except Exception as e:
                self._bridge.status_changed.emit(False, str(e))
        threading.Thread(target=_t, daemon=True).start()

    def _disconnect(self):
        self._dm.stop()
        self._bridge.status_changed.emit(False, "Disconnected")

    # ─── Status slot ─────────────────────────────────────────────
    @Slot(bool, str)
    def _on_status(self, connected: bool, message: str):
        self._set_connecting(False)
        if connected:
            broker = config.BROKER
            self._status_badge.setText(f"● LIVE — {broker.upper()}")
            self._status_badge.setStyleSheet("color:#3fb950;font-weight:bold;font-size:12px;")
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._cc_broker.setText(broker.upper())
            self._cc_status.setText("Connected")
            self._cc_status.setStyleSheet("color:#3fb950;font-weight:bold;")
            self._cc_conntime.setText(datetime.now().strftime("%H:%M:%S"))
            self._cc_mode.setText("Live" if broker != "mock" else "Simulation")
            self.connection_changed.emit(True, broker)
            if broker == "fyers":
                self._refresh_token_display()
        else:
            self._status_badge.setText("● DISCONNECTED")
            self._status_badge.setStyleSheet("color:#f85149;font-weight:bold;font-size:12px;")
            self._connect_btn.setEnabled(is_broker_active(self._broker))
            self._disconnect_btn.setEnabled(False)
            self._cc_status.setText("Disconnected")
            self._cc_status.setStyleSheet("color:#f85149;font-weight:bold;")
            self.connection_changed.emit(False, "")
        self._log_msg(message, "#3fb950" if connected else "#f85149")

    @Slot(str)
    def _on_url_ready(self, url: str):
        self._login_url = url
        self._url_display.setText(url)
        self._copy_btn.setEnabled(True)
        self._log_msg("Fyers login URL ready — opening browser…")
        webbrowser.open(url)

    # ─── Save / Load ─────────────────────────────────────────────
    def _save_all(self):
        broker = self._broker
        self._apply_fields(broker)
        config.TELEGRAM_ENABLED   = self._tg_enabled.isChecked()
        config.TELEGRAM_BOT_TOKEN = self._tg_token.text().strip()
        config.TELEGRAM_CHAT_ID   = self._tg_chat.text().strip()
        self._persist()
        self._log_msg("Credentials saved ✓")

    def _apply_fields(self, broker):
        if broker not in config.BROKER_CREDENTIALS:
            config.BROKER_CREDENTIALS[broker] = {}
        for key, widget in self._fields.items():
            config.BROKER_CREDENTIALS[broker][key] = widget.text().strip()
        # Fyers: if app_id blank but client_id set, auto-fill app_id = clientid-100
        fc = config.BROKER_CREDENTIALS.get("fyers", {})
        if broker == "fyers" and not fc.get("app_id") and fc.get("client_id"):
            fc["app_id"] = fc["client_id"] + "-100"
            if "app_id" in self._fields:
                self._fields["app_id"].setText(fc["app_id"])
        # Redirect URI default
        if broker == "fyers" and not fc.get("redirect_uri"):
            fc["redirect_uri"] = "https://trade.fyers.in/api-login/redirect-uri/index.html"

    def _persist(self):
        AUTH_DIR.mkdir(exist_ok=True)
        # Store secrets in OS keyring — credentials.json holds only metadata
        # (which keys exist, broker choice, non-sensitive flags).
        stored_keys: dict = {}
        for broker, creds in config.BROKER_CREDENTIALS.items():
            stored_keys[broker] = []
            for k, v in creds.items():
                if v and k != "token_expiry":
                    _save_secret(f"{broker}_{k}", v)
                    stored_keys[broker].append(k)
        _save_secret("telegram_bot_token", config.TELEGRAM_BOT_TOKEN or "")
        _save_secret("telegram_chat_id",   config.TELEGRAM_CHAT_ID   or "")
        payload = {
            "broker":      config.BROKER,
            "stored_keys": stored_keys,
            "telegram": {
                "enabled": config.TELEGRAM_ENABLED,
            },
            # Fallback store for environments without OS keyring
            "_fallback": _FALLBACK_STORE if not _KEYRING_OK else {},
        }
        CREDS_FILE.write_text(json.dumps(payload, indent=2))

    def _load_saved_credentials(self):
        if not CREDS_FILE.exists(): return
        try:
            data = json.loads(CREDS_FILE.read_text())
            # Restore fallback store if keyring is unavailable
            if not _KEYRING_OK:
                _FALLBACK_STORE.update(data.get("_fallback", {}))
            # Migrate old base64 format if "credentials" key present
            if "credentials" in data:
                import base64 as _b64
                for broker, creds in data["credentials"].items():
                    if broker in config.BROKER_CREDENTIALS:
                        for k, v in creds.items():
                            try:
                                plain = _b64.b64decode(v.encode()).decode() if v else ""
                            except Exception:
                                plain = v
                            if plain:
                                _save_secret(f"{broker}_{k}", plain)
                                config.BROKER_CREDENTIALS[broker][k] = plain
                # Migrate telegram
                tg = data.get("telegram", {})
                _save_secret("telegram_bot_token", _b64.b64decode(tg.get("bot_token","").encode()).decode() if tg.get("bot_token") else "")
                _save_secret("telegram_chat_id",   _b64.b64decode(tg.get("chat_id","").encode()).decode()   if tg.get("chat_id")   else "")
                # Rewrite in new format
                self._persist()
            else:
                # Normal load from keyring
                for broker, keys in data.get("stored_keys", {}).items():
                    if broker in config.BROKER_CREDENTIALS:
                        for k in keys:
                            v = _load_secret(f"{broker}_{k}")
                            if v:
                                config.BROKER_CREDENTIALS[broker][k] = v
            config.TELEGRAM_BOT_TOKEN = _load_secret("telegram_bot_token")
            config.TELEGRAM_CHAT_ID   = _load_secret("telegram_chat_id")
            tg = data.get("telegram", {})
            config.TELEGRAM_ENABLED   = tg.get("enabled", False)
            saved_broker = data.get("broker", "mock")
            if saved_broker in self.BROKERS:
                idx = list(self.BROKERS.keys()).index(saved_broker)
                self._broker_combo.setCurrentIndex(idx)
                self._broker = saved_broker
                config.BROKER = saved_broker   # tell main.py which broker to use
            self._log_msg(f"Loaded saved credentials for {saved_broker}")
            # Auto-connect after UI is fully initialised (500 ms delay)
            if saved_broker != "mock":
                QTimer.singleShot(500, self._auto_connect_if_possible)
        except Exception as e:
            logger.error(f"Load credentials error: {e}")

    # ─── Auto-save / Auto-connect ─────────────────────────────────
    def _schedule_auto_save(self):
        """Restart the debounce timer on every keystroke."""
        self._auto_save_timer.start()

    def _auto_save(self):
        """Silently persist credentials after field edits settle."""
        self._apply_fields(self._broker)
        self._persist()

    def _auto_connect_if_possible(self):
        """
        Called once on startup (500 ms after load) for non-mock brokers.
        Connects automatically if valid credentials / token are available.
        """
        broker = self._broker
        if broker == "mock" or self._connecting:
            return
        if not is_broker_active(broker):
            self._log_msg(
                f"{broker.upper()} is sleeping — auto-connect skipped", "#484f58"
            )
            return

        if broker == "fyers":
            try:
                from data.adapters.fyers_adapter import load_fyers_token
                if load_fyers_token():
                    self._log_msg("Valid Fyers token found — auto-connecting…", "#f0883e")
                    self._do_connect("fyers")
                else:
                    self._token_status.setText("⚠  TOKEN EXPIRED — generate a new one")
                    self._token_status.setStyleSheet(
                        "color:#f85149;font-size:11px;font-weight:bold;"
                    )
                    self._regen_btn.setVisible(True)
                    self._log_msg("Fyers token expired — please generate a new token", "#f85149")
            except Exception as e:
                logger.error(f"Auto-connect fyers error: {e}")
        else:
            # Dhan / Kite / Upstox: connect if access_token is saved
            creds = config.BROKER_CREDENTIALS.get(broker, {})
            if creds.get("access_token"):
                self._log_msg(
                    f"Saved token found — auto-connecting to {broker.upper()}…", "#f0883e"
                )
                self._do_connect(broker)

    # ─── Telegram test ────────────────────────────────────────────
    def _test_tg(self):
        token   = self._tg_token.text().strip()
        chat_id = self._tg_chat.text().strip()
        if not token or not chat_id:
            QMessageBox.warning(self, "Missing", "Enter Bot Token and Chat ID.")
            return
        def _t():
            from alerts.telegram_alert import TelegramAlerter
            ok = TelegramAlerter(token, chat_id).send("✅ *NiftyTrader* — Test alert")
            self._bridge.log_msg.emit(
                "Telegram test sent ✓" if ok else "Telegram test FAILED", 
                "#3fb950" if ok else "#f85149"
            )
        threading.Thread(target=_t, daemon=True).start()

    # ─── Helpers ─────────────────────────────────────────────────
    def _set_connecting(self, v):
        self._connecting = v
        self._connect_btn.setEnabled(not v)
        if v:
            self._spin_timer.start(80)
        else:
            self._spin_timer.stop()
            self._spinner_lbl.setText("")

    def _tick_spin(self):
        self._spinner_i = (self._spinner_i + 1) % len(self._spin_frames)
        self._spinner_lbl.setText(
            f"{self._spin_frames[self._spinner_i]}  Connecting to {self._broker.upper()}…"
        )

    def _copy_url(self):
        if self._login_url:
            QGuiApplication.clipboard().setText(self._login_url)
            self._log_msg("URL copied to clipboard")

    def _log_msg(self, msg: str, color: str = "#3fb950"):
        ts   = datetime.now().strftime("%H:%M:%S")
        html = (f'<span style="color:#484f58">[{ts}]</span> '
                f'<span style="color:{color}">{msg}</span><br>')
        self._log_box.insertHtml(html)
        self._log_box.verticalScrollBar().setValue(
            self._log_box.verticalScrollBar().maximum()
        )

    @Slot(str, str)
    def _log(self, msg: str, color: str):
        self._log_msg(msg, color)
