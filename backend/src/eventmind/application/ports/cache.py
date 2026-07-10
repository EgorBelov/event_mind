"""Порт `Cache` — типизированный доступ к Redis (TTL, инвалидация).

В M1 — минимальный интерфейс; наполняется под hot-path рекомендаций (M4).
"""
from __future__ import annotations

from typing import Protocol


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
