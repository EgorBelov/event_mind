"""Фикстуры integration-тестов: реальные Postgres(pgvector) + Redis через testcontainers.

Все тесты в этом пакете помечены `integration` и требуют Docker. В обычном
`pytest tests/unit` не запускаются.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

pytestmark = pytest.mark.integration

_PG_IMAGE = "pgvector/pgvector:pg16"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Поднять pgvector-контейнер, вернуть async-URL (postgresql+asyncpg://)."""
    with PostgresContainer(_PG_IMAGE, driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """Поднять Redis-контейнер, вернуть URL."""
    with RedisContainer("redis:7-alpine") as rc:
        host = rc.get_container_host_ip()
        port = rc.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
def env_urls(postgres_url: str, redis_url: str) -> Iterator[tuple[str, str]]:
    """Проставить DATABASE_URL/REDIS_URL в окружение на время теста."""
    old_db = os.environ.get("DATABASE_URL")
    old_redis = os.environ.get("REDIS_URL")
    os.environ["DATABASE_URL"] = postgres_url
    os.environ["REDIS_URL"] = redis_url
    try:
        yield postgres_url, redis_url
    finally:
        for key, val in (("DATABASE_URL", old_db), ("REDIS_URL", old_redis)):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
