"""async-SQLAlchemy engine + session-factory + health-ping.

pgvector с день-1: engine на asyncpg, `pool_pre_ping=True` (Supabase/pooler
режет idle-соединения) и `pool_recycle`. Репозитории агрегатов появятся в M1;
здесь — только транспорт и `ping_db` для `/ready`.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from eventmind.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Создать async-engine под настройки процесса."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle,
        future=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий (expire_on_commit=False — объекты живут после commit)."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def ping_db(engine: AsyncEngine) -> bool:
    """`SELECT 1` для readiness-проверки. Возвращает False при любой ошибке."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
