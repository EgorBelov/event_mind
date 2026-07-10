"""Порт `EmailChannel` — отправка письма (SMTP/провайдер за адаптером).

Часть будущей абстракции `NotificationChannel` (полная мультиканальность — M5).
В M1 используется для писем верификации и сброса пароля.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Отрендеренное письмо, готовое к отправке."""

    to: str
    subject: str
    html: str
    text: str
    headers: dict[str, str] = field(default_factory=dict)


class EmailChannel(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class EmailRenderer(Protocol):
    """Рендер писем в HTML+text (Jinja2 в infrastructure)."""

    def render_verification(self, to: str, verify_url: str) -> EmailMessage: ...
    def render_password_reset(self, to: str, reset_url: str) -> EmailMessage: ...
