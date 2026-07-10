"""arq-реализация порта `TaskQueue` (ленивое подключение) + RedisSettings.

Пул создаётся лениво на первом `enqueue`, а не на старте процесса — так API
поднимается даже без Redis (liveness не зависит от очереди), а подключение
устанавливается, только когда реально нужно поставить задачу.
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    return RedisSettings.from_dsn(redis_url)


class ArqTaskQueue:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(redis_settings_from_url(self._redis_url))
        return self._pool

    async def enqueue(self, task: str, **kwargs: object) -> None:
        pool = await self._get_pool()
        # arq.enqueue_job типизирует хвостовые kwargs строго под свои _job_id/_expires;
        # передаём job-kwargs как есть — динамический контракт очереди.
        await pool.enqueue_job(task, **kwargs)  # type: ignore[arg-type]

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
