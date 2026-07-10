"""Реестр каналов доставки. in-app пишется напрямую в инбокс (не через реестр)."""
from __future__ import annotations

from eventmind.application.ports.notifications import NotificationChannel
from eventmind.config import Settings
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.infrastructure.email.smtp import SmtpEmailChannel
from eventmind.infrastructure.notifications.email_channel import EmailNotificationChannel
from eventmind.infrastructure.notifications.telegram_channel import TelegramNotificationChannel


def build_notification_channels(settings: Settings) -> dict[ChannelType, NotificationChannel]:
    channels: dict[ChannelType, NotificationChannel] = {
        ChannelType.EMAIL: EmailNotificationChannel(SmtpEmailChannel(settings)),
    }
    if settings.bot_token:
        channels[ChannelType.TELEGRAM] = TelegramNotificationChannel(settings.bot_token)
    return channels
