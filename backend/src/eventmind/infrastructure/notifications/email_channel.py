"""EmailNotificationChannel — доставка уведомления письмом (поверх EmailChannel)."""
from __future__ import annotations

from eventmind.application.ports.email import EmailChannel, EmailMessage
from eventmind.application.ports.notifications import NotificationMessage
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.infrastructure.telemetry.metrics import NOTIFICATIONS_DELIVERED_TOTAL


class EmailNotificationChannel:
    channel_type = ChannelType.EMAIL

    def __init__(self, email: EmailChannel) -> None:
        self._email = email

    async def send(self, address: str, message: NotificationMessage) -> None:
        headers = {}
        if message.unsubscribe_url:
            headers["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
        try:
            await self._email.send(
                EmailMessage(
                    to=address,
                    subject=message.subject,
                    html=message.html,
                    text=message.text,
                    headers=headers,
                )
            )
        except Exception:
            NOTIFICATIONS_DELIVERED_TOTAL.labels("email", "error").inc()
            raise
        NOTIFICATIONS_DELIVERED_TOTAL.labels("email", "success").inc()
