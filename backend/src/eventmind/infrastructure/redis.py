"""Redis-клиент: брокер очереди (arq), кэш, rate-limit, лидер-локи.

Здесь — только фабрика клиента и health-ping для `/ready`. Типизированный
`Cache`-порт и arq-`TaskQueue` появятся в M1.
"""
from __future__ import annotations

from redis.asyncio import Redis

from eventmind.config import Settings

# Псевдоним для читаемости сигнатур (decode_responses=True → ответы строками).
RedisClient = Redis


def create_redis(settings: Settings) -> RedisClient:
    """Создать async Redis-клиент из настроек процесса."""
    client: RedisClient = Redis.from_url(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )
    return client


async def ping_redis(client: RedisClient) -> bool:
    """`PING` для readiness-проверки. Возвращает False при любой ошибке."""
    try:
        return bool(await client.ping())
    except Exception:
        return False
