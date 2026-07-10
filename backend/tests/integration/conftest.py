"""Фикстуры integration-тестов: реальные Postgres(pgvector) + Redis через testcontainers.

Все тесты в этом пакете помечены `integration` и требуют Docker. В обычном
`pytest tests/unit` не запускаются.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from eventmind.config import Settings
from eventmind.infrastructure.db.engine import create_session_factory

pytestmark = pytest.mark.integration

_PG_IMAGE = "pgvector/pgvector:pg16"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.fixture(scope="session")
def migrated_db(postgres_url: str) -> str:
    """Применить `alembic upgrade head` к контейнерной БД один раз за сессию."""
    env = {**os.environ, "DATABASE_URL": postgres_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return postgres_url


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


@pytest.fixture
def settings(migrated_db: str, redis_url: str) -> Settings:
    """Настройки для integration-теста поверх контейнеров (со схемой)."""
    return Settings(
        database_url=migrated_db,
        redis_url=redis_url,
        log_json=False,
        jwt_secret="test-secret-key-of-sufficient-length-1234",
        api_shared_secret="internal-secret",
        environment="dev",
    )


@pytest.fixture
async def clean_tables(settings: Settings) -> None:
    """Очистить таблицы аккаунтов перед тестом (изоляция при общей БД)."""
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text(
                    "TRUNCATE outbox, one_time_tokens, notification_preferences, "
                    "user_channels, users, event_topics, events, raw_events, topics "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(settings: Settings) -> async_sessionmaker:
    engine = create_async_engine(settings.database_url)
    return create_session_factory(engine)
