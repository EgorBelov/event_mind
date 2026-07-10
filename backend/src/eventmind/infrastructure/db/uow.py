"""`SqlAlchemyUnitOfWork` — транзакционная граница + запись outbox в той же транзакции.

Доменные события, накопленные за use-case, сериализуются и пишутся в таблицу
`outbox` тем же `commit()`, что и изменения агрегатов. Либо всё, либо ничего —
рассылки не теряются и не «утекают» при откате.
"""
from __future__ import annotations

from datetime import datetime
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.repositories import (
    NotificationPreferenceRepository,
    TokenRepository,
    UserChannelRepository,
    UserRepository,
)
from eventmind.domain.accounts.events import DomainEvent
from eventmind.infrastructure.db.models import OutboxModel
from eventmind.infrastructure.db.repositories import (
    SqlAlchemyNotificationPreferenceRepository,
    SqlAlchemyTokenRepository,
    SqlAlchemyUserChannelRepository,
    SqlAlchemyUserRepository,
)


def _json_safe(value: object) -> object:
    """Привести payload события к JSON-совместимому виду (datetime → isoformat)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


class SqlAlchemyUnitOfWork:
    """Единица работы поверх одной async-сессии."""

    # Репозитории типизированы портами (не конкретными классами) — так
    # SqlAlchemyUnitOfWork структурно удовлетворяет протокол UnitOfWork.
    users: UserRepository
    channels: UserChannelRepository
    preferences: NotificationPreferenceRepository
    tokens: TokenRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._events: list[DomainEvent] = []

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._events = []
        session = self._session
        self.users = SqlAlchemyUserRepository(session)
        self.channels = SqlAlchemyUserChannelRepository(session)
        self.preferences = SqlAlchemyNotificationPreferenceRepository(session)
        self.tokens = SqlAlchemyTokenRepository(session)
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

    def add_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    async def commit(self) -> None:
        assert self._session is not None
        # Сериализуем накопленные события в outbox в той же транзакции.
        for event in self._events:
            payload = {k: _json_safe(v) for k, v in event.payload().items()}
            self._session.add(OutboxModel(event_type=event.event_type, payload=payload))
        self._events = []
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()
