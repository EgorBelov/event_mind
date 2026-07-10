"""Хеширование паролей на argon2id (порт `PasswordHasher`)."""
from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerifyMismatchError


class Argon2PasswordHasher:
    """Обёртка над argon2-cffi с параметрами по умолчанию (argon2id)."""

    def __init__(self) -> None:
        self._ph = _Argon2()

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._ph.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._ph.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
