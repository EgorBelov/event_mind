"""`OutboxProcessor` — читает необработанные события и диспетчеризует в обработчики.

Обработчик регистрируется по `event_type` (например, `user.registered` →
отправка письма верификации). Ошибка одного сообщения помечается `failed` и
не блокирует остальные (at-least-once: обработчики должны быть идемпотентны).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from eventmind.application.ports.outbox import OutboxMessage, OutboxStore

EventHandler = Callable[[dict[str, object]], Awaitable[None]]

_logger = structlog.get_logger("eventmind.outbox")


class OutboxProcessor:
    def __init__(self, store: OutboxStore, handlers: dict[str, EventHandler]) -> None:
        self._store = store
        self._handlers = handlers

    async def process_pending(self, limit: int = 100) -> int:
        """Обработать пачку событий. Возвращает число успешно обработанных."""
        messages = await self._store.fetch_unprocessed(limit=limit)
        processed = 0
        for message in messages:
            if await self._handle(message):
                processed += 1
        return processed

    async def _handle(self, message: OutboxMessage) -> bool:
        handler = self._handlers.get(message.event_type)
        if handler is None:
            # Нет обработчика — не ошибка релея: помечаем обработанным, чтобы
            # не крутить бесконечно. (Регистрация обработчиков — забота сборки.)
            _logger.warning("outbox_no_handler", event_type=message.event_type, id=message.id)
            await self._store.mark_processed(message.id)
            return False
        try:
            await handler(message.payload)
        except Exception as exc:  # обработчик упал — пометить failed, продолжить
            _logger.error(
                "outbox_handler_failed",
                event_type=message.event_type,
                id=message.id,
                error=str(exc),
            )
            await self._store.mark_failed(message.id, str(exc))
            return False
        await self._store.mark_processed(message.id)
        return True
