"""Одноразовые секреты + часы (порты `SecretTokenGenerator`, `Clock`).

Генерируем криптостойкий url-safe токен; в БД храним его SHA-256-хеш, сырое
значение уходит пользователю (в письме/deep-link) и больше нигде не живёт.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


class Sha256SecretTokenGenerator:
    def __init__(self, *, nbytes: int = 32) -> None:
        self._nbytes = nbytes

    def generate(self) -> tuple[str, str]:
        raw = secrets.token_urlsafe(self._nbytes)
        return raw, self.hash(raw)

    def hash(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
