"""Порты репозиториев событий (raw_events / events / topics)."""
from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol

from eventmind.domain.events.entities import Event, RawEvent
from eventmind.domain.events.value_objects import RawEventStatus


class RawEventRepository(Protocol):
    async def add_if_absent(self, raw: RawEvent) -> RawEvent | None:
        """Идемпотентно добавить сырое событие. None — уже существует (source+url)."""
        ...

    async def get_by_id(self, raw_id: int) -> RawEvent | None: ...

    async def fetch_for_processing(
        self, statuses: list[RawEventStatus], *, limit: int, max_retries: int
    ) -> list[RawEvent]:
        """Взять пачку сырых событий на обработку (raw + failed с retry_count<max)."""
        ...

    async def update(self, raw: RawEvent) -> None: ...

    async def count_by_status(self) -> dict[str, int]: ...


class EventRepository(Protocol):
    async def exists_by_source_url(self, source_url: str) -> bool: ...
    async def add(self, event: Event, topic_ids: list[int]) -> Event: ...
    async def count(self) -> int: ...


class TopicRepository(Protocol):
    async def ensure_codes(self, codes: list[str]) -> dict[str, int]:
        """Гарантировать строки topics для кодов; вернуть {code: topic_id}."""
        ...


class EventsUnitOfWork(Protocol):
    """Транзакционная граница ingestion: raw_events + events + topics на общей сессии."""

    raw_events: RawEventRepository
    events: EventRepository
    topics: TopicRepository

    async def __aenter__(self) -> EventsUnitOfWork: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


EventsUnitOfWorkFactory = Callable[[], EventsUnitOfWork]
