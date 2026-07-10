"""Доменные сущности аккаунтов (чистые, без ORM/I-O).

Маппинг на таблицы делают репозитории в `infrastructure`. `id=None` —
сущность ещё не персистилась.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from eventmind.domain.accounts.errors import AccountInactive
from eventmind.domain.accounts.value_objects import (
    ChannelType,
    DigestFrequency,
)


@dataclass
class User:
    """Аккаунт пользователя. Идентичность — email, не Telegram."""

    email: str
    password_hash: str | None  # None допустимо только для будущего OAuth-only
    id: int | None = None
    email_verified: bool = False
    is_active: bool = True
    # Соц-логин (Google) — M6.
    oauth_provider: str | None = None
    oauth_sub: str | None = None
    # Предпочтения для rule-скоринга (наполняются в вебе).
    city: str | None = None
    preferred_format: str | None = None
    created_at: datetime | None = None

    def mark_email_verified(self) -> None:
        self.email_verified = True

    def set_password_hash(self, password_hash: str) -> None:
        self.password_hash = password_hash

    def ensure_can_login(self) -> None:
        """Аккаунт активен? Иначе — доменная ошибка."""
        if not self.is_active:
            raise AccountInactive("Аккаунт деактивирован")


@dataclass
class UserChannel:
    """Канал доставки, привязанный к аккаунту."""

    user_id: int
    type: ChannelType
    address: str  # email-адрес или telegram chat_id (строкой)
    id: int | None = None
    verified: bool = False
    enabled: bool = True
    created_at: datetime | None = None

    def mark_verified(self) -> None:
        self.verified = True


@dataclass
class NotificationPreference:
    """Настройки уведомлений аккаунта."""

    user_id: int
    digest_frequency: DigestFrequency = DigestFrequency.DAILY
    email_enabled: bool = True
    telegram_enabled: bool = False
    # Тихие часы (локальный час 0..23); None — не заданы.
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    id: int | None = None

    def is_channel_enabled(self, channel: ChannelType) -> bool:
        if channel is ChannelType.EMAIL:
            return self.email_enabled
        if channel is ChannelType.TELEGRAM:
            return self.telegram_enabled
        return False


@dataclass
class OneTimeToken:
    """Одноразовый токен (верификация email / сброс пароля / привязка Telegram).

    Хранится хеш токена, а не сырое значение (сырое уходит пользователю в письме
    и живёт только в момент выдачи). `consumed_at`/`expires_at` — контроль
    одноразовости и TTL.
    """

    user_id: int | None
    purpose: str
    token_hash: str
    expires_at: datetime
    id: int | None = None
    consumed_at: datetime | None = None
    # Доп. полезная нагрузка (например, chat_id для telegram-link).
    payload: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None

    def is_usable(self, *, now: datetime) -> bool:
        return self.consumed_at is None and self.expires_at > now

    def consume(self, *, now: datetime) -> None:
        self.consumed_at = now
