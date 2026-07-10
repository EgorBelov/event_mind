"""Доменные события аккаунтов → пишутся в outbox в одной транзакции с агрегатом.

Событие несёт минимум данных, нужных обработчику (отправка письма). Сырой
одноразовый токен кладём в событие намеренно: он нужен для ссылки в письме и
нигде больше в открытом виде не хранится (в БД — только хеш).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DomainEvent:
    """База доменного события."""

    event_type: str = field(init=False, default="domain.event")

    def payload(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("event_type", None)
        return data


@dataclass(frozen=True)
class UserRegistered(DomainEvent):
    """Зарегистрирован новый аккаунт — нужно отправить письмо верификации."""

    event_type: str = field(init=False, default="user.registered")
    user_id: int = 0
    email: str = ""
    verification_token: str = ""
    occurred_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class PasswordResetRequested(DomainEvent):
    """Запрошен сброс пароля — нужно отправить письмо со ссылкой сброса."""

    event_type: str = field(init=False, default="password.reset_requested")
    user_id: int = 0
    email: str = ""
    reset_token: str = ""
    occurred_at: datetime = field(default_factory=_utcnow)
