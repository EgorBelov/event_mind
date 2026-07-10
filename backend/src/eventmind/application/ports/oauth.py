"""Порт проверки Google id_token (соц-логин)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    email: str
    sub: str


class GoogleTokenVerifier(Protocol):
    async def verify(self, id_token: str) -> GoogleIdentity | None:
        """Проверить id_token и вернуть личность, либо None при невалидности."""
        ...
