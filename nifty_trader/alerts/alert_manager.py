"""
alerts/alert_manager.py
Handles all alert delivery: popup, sound, Telegram.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Optional, Callable, List
import os

import config

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Receives alert objects and dispatches them to:
      1. In-app notification (via callback to UI)
      2. Desktop system popup
      3. Sound beep (via platform beep)
      4. Telegram message (if configured)
    """

    def __init__(self):
        self._ui_callbacks: List[Callable] = []
        self._telegram: Optional["TelegramAlerter"] = None
        self._sound_enabled  = config.SOUND_ALERTS_ENABLED
        self._popup_enabled  = config.POPUP_ALERTS_ENABLED
        # Track dispatched alert_ids — UI callback fires every tick (live updates),
        # but sound/popup/Telegram fire only ONCE per unique alert.
        self._dispatched_ids: set = set()

        if config.TELEGRAM_ENABLED:
            try:
                from alerts.telegram_alert import TelegramAlerter
                self._telegram = TelegramAlerter()
                logger.info("Telegram alerts enabled")
            except Exception as e:
                logger.warning(f"Telegram alerts disabled (init failed): {e}")

    def add_ui_callback(self, fn: Callable):
        """Register UI notification callback."""
        self._ui_callbacks.append(fn)

    def fire(self, alert_obj):
        """Dispatch an alert to all channels."""
        from engines.signal_aggregator import EarlyMoveAlert, TradeSignal

        # S4 fix: confirmed signals get a distinct notification path.
        if isinstance(alert_obj, TradeSignal) and getattr(alert_obj, "is_confirmed", False):
            self._handle_confirmed_signal(alert_obj)
        elif isinstance(alert_obj, TradeSignal):
            self._handle_trade_signal(alert_obj)
        elif isinstance(alert_obj, EarlyMoveAlert):
            self._handle_early_alert(alert_obj)

    def _handle_confirmed_signal(self, signal):
        """Candle-close activation confirmed — distinct 2-beep + star prefix."""
        title   = f"✅ ACTIVATION CONFIRMED — {signal.index_name}"
        message = (
            f"Direction: {signal.direction}\n"
            f"Confidence: {signal.confidence_score:.1f}%\n"
            f"Instrument: {signal.suggested_instrument}\n"
            f"Entry: {signal.entry_reference:.2f}  SL: {signal.stop_loss_reference:.2f}\n"
            f"T1: {signal.target1:.2f}  T2: {signal.target2:.2f}  T3: {signal.target3:.2f}"
        )
        self._dispatch(title, message, sound_count=2, is_trade=True, alert_obj=signal)

    def _handle_early_alert(self, alert):
        title   = f"⚡ EARLY MOVE — {alert.index_name}"
        message = (
            f"Direction: {alert.direction}\n"
            f"Confidence: {alert.confidence_score:.1f}%\n"
            f"Engines: {', '.join(alert.engines_triggered)}\n"
            f"Spot: {alert.spot_price:.2f} | PCR: {alert.pcr:.3f}"
        )
        self._dispatch(title, message, sound_count=1, is_trade=False, alert_obj=alert)

    def _handle_trade_signal(self, signal):
        title   = f"🎯 TRADE SIGNAL — {signal.index_name}"
        message = (
            f"Direction: {signal.direction}\n"
            f"Confidence: {signal.confidence_score:.1f}%\n"
            f"Instrument: {signal.suggested_instrument}\n"
            f"Entry Ref: {signal.entry_reference:.2f}\n"
            f"Stop Loss: {signal.stop_loss_reference:.2f}\n"
            f"Target: {signal.target_reference:.2f}"
        )
        self._dispatch(title, message, sound_count=3, is_trade=True, alert_obj=signal)

    def _dispatch(self, title, message, sound_count, is_trade, alert_obj):
        # Always notify UI callbacks (live confidence updates every tick)
        for cb in self._ui_callbacks:
            try:
                cb(alert_obj)
            except Exception as e:
                logger.error(f"UI callback error: {e}")

        # Sound / popup / Telegram — fire ONCE per unique alert_id only
        alert_id = getattr(alert_obj, "alert_id", None)
        is_new = alert_id is None or alert_id not in self._dispatched_ids
        if alert_id is not None:
            self._dispatched_ids.add(alert_id)

        if not is_new:
            return   # UI already updated above; skip repeat notifications

        # Sound alert
        if self._sound_enabled:
            threading.Thread(
                target=self._play_sound,
                args=(sound_count, is_trade),
                daemon=True
            ).start()

        # System popup (cross-platform)
        if self._popup_enabled:
            threading.Thread(
                target=self._show_popup,
                args=(title, message),
                daemon=True
            ).start()

        # Telegram
        if self._telegram:
            full_text = f"*{title}*\n{message}"
            threading.Thread(
                target=self._telegram.send,
                args=(full_text,),
                daemon=True
            ).start()

        safe_title = title.encode("ascii", errors="replace").decode("ascii")
        logger.info(f"Alert fired: {safe_title}")

    @staticmethod
    def _play_sound(count: int, is_trade: bool):
        try:
            import winsound  # Windows
            freq = 1000 if is_trade else 800
            for _ in range(count):
                winsound.Beep(freq, 300)
                time.sleep(0.1)
        except ImportError:
            try:
                # Linux / macOS
                for _ in range(count):
                    os.system("echo -e '\a'")
                    time.sleep(0.1)
            except Exception:
                pass

    @staticmethod
    def _show_popup(title: str, message: str):
        """Cross-platform desktop notification."""
        try:
            from plyer import notification  # type: ignore
            notification.notify(
                title=title,
                message=message,
                app_name="NiftyTrader",
                timeout=10,
            )
        except ImportError:
            try:
                # Fallback: Windows toast via win10toast
                from win10toast import ToastNotifier  # type: ignore
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=8, threaded=True)
            except ImportError:
                logger.debug("No popup library available (install plyer)")
