"""Порт `EventSource` — контракт источника ingestion (плагин-реестр).

Реализации (habr/rss/kudago/…) живут в `infrastructure/sources` и
регистрируются в реестре. Источник только достаёт сырьё — нормализация и
персистентность делаются пайплайном.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawEventDraft:
    """Сырое событие «как пришло из источника»."""

    title: str
    raw_description: str
    source_url: str | None = None


class EventSource(Protocol):
    @property
    def name(self) -> str: ...

    async def fetch(self, limit: int = 20) -> list[RawEventDraft]:
        """Скачать до `limit` сырых событий. Ошибки источника → пустой список."""
        ...
