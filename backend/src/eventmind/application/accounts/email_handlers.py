"""Обработчики доменных событий аккаунтов → письма (для OutboxProcessor).

Собираются в композит-руте worker'а: связывают `EmailChannel` + `EmailRenderer`
+ базовый URL веба. Идемпотентны на уровне доставки (повторная отправка письма
безопасна: at-least-once из outbox).
"""
from __future__ import annotations

from eventmind.application.outbox.processor import EventHandler
from eventmind.application.ports.email import EmailChannel, EmailRenderer


def make_user_registered_handler(
    channel: EmailChannel, renderer: EmailRenderer, public_web_url: str
) -> EventHandler:
    async def handle(payload: dict[str, object]) -> None:
        to = str(payload["email"])
        token = str(payload["verification_token"])
        verify_url = f"{public_web_url.rstrip('/')}/verify-email?token={token}"
        await channel.send(renderer.render_verification(to, verify_url))

    return handle


def make_password_reset_handler(
    channel: EmailChannel, renderer: EmailRenderer, public_web_url: str
) -> EventHandler:
    async def handle(payload: dict[str, object]) -> None:
        to = str(payload["email"])
        token = str(payload["reset_token"])
        reset_url = f"{public_web_url.rstrip('/')}/reset-password?token={token}"
        await channel.send(renderer.render_password_reset(to, reset_url))

    return handle
