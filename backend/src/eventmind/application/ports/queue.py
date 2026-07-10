"""Порт `TaskQueue` — постановка фоновых задач (arq за адаптером).

Идемпотентные ключи и ретраи — забота адаптера/воркера. В M1 используется,
чтобы после commit'а поставить обработку outbox в очередь.
"""
from __future__ import annotations

from typing import Protocol


class TaskQueue(Protocol):
    async def enqueue(self, task: str, **kwargs: object) -> None: ...
