"""Порт хранилища outbox для процессора-релея.

Запись в outbox делает `UnitOfWork` (в транзакции агрегата). Чтение и
пометку обрабатывает `OutboxProcessor` (обычно в worker'е) через этот порт.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: int
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class OutboxStore(Protocol):
    async def fetch_unprocessed(self, limit: int = 100) -> list[OutboxMessage]: ...
    async def mark_processed(self, message_id: int) -> None: ...
    async def mark_failed(self, message_id: int, error: str) -> None: ...
