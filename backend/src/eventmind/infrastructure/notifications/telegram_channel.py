"""TelegramNotificationChannel — доставка в Telegram через Bot API sendMessage.

Порт из v1 (`legacy/app/scheduler/digest.py`): текст шлётся plain-text (без
parse_mode), чтобы дайджест не терялся из-за строгого HTML-парсера Telegram.
"""
from __future__ import annotations

import httpx

from eventmind.application.ports.notifications import NotificationMessage
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.infrastructure.telemetry.metrics import NOTIFICATIONS_DELIVERED_TOTAL


class TelegramNotificationChannel:
    channel_type = ChannelType.TELEGRAM

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token

    async def send(self, address: str, message: NotificationMessage) -> None:
        if not self._bot_token:
            raise RuntimeError("BOT_TOKEN не задан — Telegram-доставка недоступна")
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    url, json={"chat_id": address, "text": message.text}
                )
                resp.raise_for_status()
        except Exception:
            NOTIFICATIONS_DELIVERED_TOTAL.labels("telegram", "error").inc()
            raise
        NOTIFICATIONS_DELIVERED_TOTAL.labels("telegram", "success").inc()
