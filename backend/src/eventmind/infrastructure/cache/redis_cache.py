"""Redis-реализация порта `Cache`."""
from __future__ import annotations

from eventmind.infrastructure.redis import RedisClient


class RedisCache:
    def __init__(self, client: RedisClient) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        return value if value is None else str(value)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)
