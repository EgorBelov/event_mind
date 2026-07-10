"""Порт `UnitOfWork` — транзакционная граница + outbox в той же транзакции.

Ключевая гарантия надёжности: доменные события, накопленные за use-case,
пишутся в таблицу `outbox` **атомарно** с изменениями агрегатов. Так рассылки
и фоновые задачи не теряются при сбое между «сохранили» и «поставили в очередь».
"""
from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol

from eventmind.application.ports.repositories import (
    NotificationPreferenceRepository,
    TokenRepository,
    UserChannelRepository,
    UserRepository,
)
from eventmind.domain.accounts.events import DomainEvent


class UnitOfWork(Protocol):
    """Единица работы: репозитории на общей сессии + буфер доменных событий."""

    users: UserRepository
    channels: UserChannelRepository
    preferences: NotificationPreferenceRepository
    tokens: TokenRepository

    async def __aenter__(self) -> UnitOfWork: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def add_event(self, event: DomainEvent) -> None:
        """Поставить доменное событие в очередь на запись в outbox при commit."""
        ...

    async def commit(self) -> None:
        """Записать изменения + накопленные события в outbox одной транзакцией."""
        ...

    async def rollback(self) -> None: ...


# Фабрика UoW (композит-рут создаёт свежую единицу работы на каждый use-case).
UnitOfWorkFactory = Callable[[], UnitOfWork]
