"""Порты безопасности: хеширование паролей, JWT, одноразовые токены, часы."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class PasswordHasher(Protocol):
    """Хеширование и проверка паролей (argon2 в infrastructure)."""

    def hash(self, password: str) -> str: ...
    def verify(self, password: str, password_hash: str) -> bool: ...
    def needs_rehash(self, password_hash: str) -> bool: ...


class TokenService(Protocol):
    """Пользовательские JWT (access/refresh)."""

    def create_access_token(self, subject: str, extra: dict[str, str] | None = None) -> str: ...
    def create_refresh_token(self, subject: str) -> str: ...
    def create_purpose_token(self, subject: str, purpose: str, *, ttl_seconds: int) -> str:
        """Долгоживущий токен под конкретную цель (напр. unsubscribe-ссылка)."""
        ...

    def decode(self, token: str) -> dict[str, object]:
        """Вернуть claims. Бросает при истечении/невалидной подписи."""
        ...


class SecretTokenGenerator(Protocol):
    """Генерация одноразовых секретов (верификация/сброс/привязка).

    Возвращает пару (raw, hash): raw уходит пользователю (в письме/ссылке),
    в БД хранится только hash.
    """

    def generate(self) -> tuple[str, str]: ...
    def hash(self, raw: str) -> str: ...


class Clock(Protocol):
    """Источник времени (для детерминизма в тестах)."""

    def now(self) -> datetime: ...
