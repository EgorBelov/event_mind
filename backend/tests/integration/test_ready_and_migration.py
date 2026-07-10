"""Integration: /ready против живых Postgres+Redis и применение первой миграции."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_ready_true_with_live_services(postgres_url: str, redis_url: str) -> None:
    settings = Settings(database_url=postgres_url, redis_url=redis_url, log_json=False)
    with TestClient(create_app(settings)) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "redis": True}


def test_ready_false_when_redis_down(postgres_url: str) -> None:
    settings = Settings(
        database_url=postgres_url,
        redis_url="redis://127.0.0.1:6390/0",  # закрытый порт
        log_json=False,
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] is False


def test_migration_creates_pgvector_and_marker(env_urls: tuple[str, str]) -> None:
    db_url, _ = env_urls
    # alembic env.py читает DATABASE_URL из окружения (проставлен в env_urls).
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    async def _verify() -> None:
        engine = create_async_engine(db_url)
        try:
            async with engine.connect() as conn:
                ext = await conn.scalar(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
                assert ext == 1
                marker = await conn.scalar(
                    text("SELECT component FROM schema_marker WHERE component = 'm0-skeleton'")
                )
                assert marker == "m0-skeleton"
        finally:
            await engine.dispose()

    asyncio.run(_verify())
