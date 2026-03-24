"""
alerts/telegram_alert.py
Sends alerts to Telegram via Bot API.

Setup:
  1. Create a bot via @BotFather → get BOT_TOKEN
  2. Start a conversation → get CHAT_ID
  3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED=true
"""

import logging
import requests
from typing import Optional
import config

logger = logging.getLogger(__name__)


class TelegramAlerter:
    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        token: str = config.TELEGRAM_BOT_TOKEN,
        chat_id: str = config.TELEGRAM_CHAT_ID,
    ):
        self.token   = token
        self.chat_id = chat_id
        self._url    = self.BASE_URL.format(token=token)

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not configured")
            return False

        try:
            resp = requests.post(
                self._url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.debug("Telegram message sent")
                return True
            else:
                logger.error(f"Telegram error: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_alert(self, alert_obj) -> bool:
        """Format and send a NiftyTrader alert."""
        from engines.signal_aggregator import TradeSignal, EarlyMoveAlert

        if isinstance(alert_obj, TradeSignal):
            text = (
                f"🎯 *TRADE SIGNAL — {alert_obj.index_name}*\n\n"
                f"Direction: `{alert_obj.direction}`\n"
                f"Confidence: `{alert_obj.confidence_score:.1f}%`\n"
                f"Instrument: `{alert_obj.suggested_instrument}`\n"
                f"Entry: `{alert_obj.entry_reference:.2f}`\n"
                f"SL: `{alert_obj.stop_loss_reference:.2f}`\n"
                f"Target: `{alert_obj.target_reference:.2f}`\n"
                f"Spot: `{alert_obj.spot_price:.2f}`\n"
                f"PCR: `{alert_obj.pcr:.3f}`\n"
                f"Time: `{alert_obj.timestamp.strftime('%H:%M:%S')}`"
            )
        elif isinstance(alert_obj, EarlyMoveAlert):
            engines_str = " | ".join(alert_obj.engines_triggered)
            text = (
                f"⚡ *EARLY MOVE — {alert_obj.index_name}*\n\n"
                f"Direction: `{alert_obj.direction}`\n"
                f"Confidence: `{alert_obj.confidence_score:.1f}%`\n"
                f"Engines: `{engines_str}`\n"
                f"Spot: `{alert_obj.spot_price:.2f}`\n"
                f"PCR: `{alert_obj.pcr:.3f}`\n"
                f"Time: `{alert_obj.timestamp.strftime('%H:%M:%S')}`"
            )
        else:
            text = str(alert_obj)

        return self.send(text)
