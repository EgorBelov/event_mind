"""Порт поиска событий: строгий поиск по фильтрам, полнотекстовый и семантический
(три ретривера гибридного поиска, P1 №7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from eventmind.domain.events.entities import Event


@dataclass(slots=True)
class SearchQuery:
    """Канонизированные фильтры для SQL-поиска."""

    date_from: str | None = None
    date_to: str | None = None
    city: str | None = None
    event_type: str | None = None
    format: str | None = None
    topics: list[str] = field(default_factory=list)
    free_text: str = ""


class SearchRepository(Protocol):
    async def search(
        self, query: SearchQuery, *, limit: int, now: datetime
    ) -> list[Event]:
        """Строгий поиск: все фильтры, free_text — подстрокой, по дате."""
        ...

    async def text_search(
        self, query: SearchQuery, text: str, *, limit: int, now: datetime
    ) -> list[Event]:
        """Полнотекстовый поиск (морфология, ранжирование по релевантности) по
        `text` с жёсткими фильтрами `query` (даты, город, тип, формат)."""
        ...

    async def semantic_search(
        self,
        query: SearchQuery,
        vector: list[float],
        *,
        limit: int,
        now: datetime,
        min_similarity: float,
    ) -> list[Event]:
        """kNN по эмбеддингу (cosine ≥ min_similarity) с жёсткими фильтрами `query`."""
        ...

    async def get_event(self, event_id: int) -> Event | None: ...

    async def get_events(self, event_ids: list[int]) -> list[Event]:
        """События по id в порядке `event_ids` (отсутствующие пропускаются)."""
        ...
