"""SMTP-адаптер `EmailChannel` на aiosmtplib.

dev: Mailhog (host=mailhog:1025, без TLS). prod: Yandex (smtp.yandex.ru:465,
SSL) или Mail.ru (smtp.mail.ru:465, SSL) с app-password. Выбор TLS/SSL — по
настройкам `SMTP_USE_TLS` (STARTTLS/587) / `SMTP_USE_SSL` (SSL/465).
"""
from __future__ import annotations

from email.message import EmailMessage as MimeMessage

import aiosmtplib

from eventmind.application.ports.email import EmailMessage
from eventmind.config import Settings


class SmtpEmailChannel:
    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._use_tls = settings.smtp_use_tls  # STARTTLS
        self._use_ssl = settings.smtp_use_ssl  # implicit TLS (465)
        self._from = settings.email_from

    def _build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self._from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        for key, value in message.headers.items():
            mime[key] = value
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        return mime

    async def send(self, message: EmailMessage) -> None:
        mime = self._build(message)
        await aiosmtplib.send(
            mime,
            hostname=self._host,
            port=self._port,
            username=self._user or None,
            password=self._password or None,
            use_tls=self._use_ssl,       # implicit TLS (465)
            start_tls=self._use_tls or None,  # STARTTLS (587); None → авто
        )
