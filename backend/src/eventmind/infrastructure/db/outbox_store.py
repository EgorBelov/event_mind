"""`SqlAlchemyOutboxStore` — чтение/пометка outbox для `OutboxProcessor`.

Работает в собственной сессии (обычно в worker'е). `SELECT ... FOR UPDATE
SKIP LOCKED` даёт безопасную конкурентную обработку несколькими воркерами.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.outbox import OutboxMessage
from eventmind.infrastructure.db.models import OutboxModel


class SqlAlchemyOutboxStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def fetch_unprocessed(self, limit: int = 100) -> list[OutboxMessage]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OutboxModel)
                .where(OutboxModel.status == "pending")
                .order_by(OutboxModel.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = result.scalars().all()
            return [
                OutboxMessage(
                    id=row.id,
                    event_type=row.event_type,
                    payload=dict(row.payload),
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def mark_processed(self, message_id: int) -> None:
        async with self._session_factory() as session:
            model = await session.get(OutboxModel, message_id)
            if model is not None:
                model.status = "processed"
                model.processed_at = datetime.now(UTC)
                model.error = None
                await session.commit()

    async def mark_failed(self, message_id: int, error: str) -> None:
        async with self._session_factory() as session:
            model = await session.get(OutboxModel, message_id)
            if model is not None:
                model.status = "failed"
                model.error = error[:2000]
                await session.commit()
