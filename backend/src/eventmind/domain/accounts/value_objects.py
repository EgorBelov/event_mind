"""Value-objects домена аккаунтов."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ChannelType(str, Enum):
    """Тип канала доставки, привязанного к аккаунту."""

    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBPUSH = "webpush"  # закладка на будущее (VAPID/Service Worker)


class DigestFrequency(str, Enum):
    """Частота дайджеста рекомендаций."""

    OFF = "off"
    DAILY = "daily"
    WEEKLY = "weekly"


class TokenPurpose(str, Enum):
    """Назначение одноразового токена."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    TELEGRAM_LINK = "telegram_link"


# Практичный, не-педантичный шаблон email: локальная часть @ домен с точкой.
# Строгую валидацию делает pydantic EmailStr на границе API; здесь — санити-чек
# на случай доменных вызовов в обход API.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class Email:
    """Нормализованный email (lower-case, без пробелов по краям)."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError(f"Некорректный email: {self.value!r}")
        # frozen — присваиваем через object.__setattr__
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
