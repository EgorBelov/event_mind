"""`SqlAlchemyEventsUnitOfWork` — транзакционная граница ingestion.

raw_events + events + topics на общей сессии. Без outbox (доменных событий у
ingestion пока нет) — только атомарность записи пачки нормализации.
"""
from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.events import (
    EventRepository,
    RawEventRepository,
    TopicRepository,
)
from eventmind.infrastructure.db.event_repositories import (
    SqlAlchemyEventRepository,
    SqlAlchemyRawEventRepository,
    SqlAlchemyTopicRepository,
)


class SqlAlchemyEventsUnitOfWork:
    raw_events: RawEventRepository
    events: EventRepository
    topics: TopicRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyEventsUnitOfWork:
        self._session = self._session_factory()
        self.raw_events = SqlAlchemyRawEventRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
        self.topics = SqlAlchemyTopicRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()
