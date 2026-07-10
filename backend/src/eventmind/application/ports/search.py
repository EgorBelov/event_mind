"""Порт поиска событий (строгий SQL-поиск по фильтрам + upcoming)."""
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
    ) -> list[Event]: ...

    async def get_event(self, event_id: int) -> Event | None: ...
