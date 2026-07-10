"""Порты доставки уведомлений: `NotificationChannel` + `NotificationsUnitOfWork`.

Одна абстракция доставки — разные реализации (email/telegram/in-app; web-push
позже). Выбор канала — по `NotificationPreference`; контент рендерится под канал.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Protocol

from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.domain.notifications.entities import Notification, NotificationType


@dataclass(slots=True)
class NotificationMessage:
    """Канал-агностичный контент уведомления (рендерится под каждый канал)."""

    subject: str
    text: str
    html: str
    unsubscribe_url: str | None = None
    items: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ChannelInfo:
    type: ChannelType
    address: str
    verified: bool
    enabled: bool


@dataclass(slots=True)
class DeliveryContext:
    """Всё нужное для доставки дайджеста одному пользователю."""

    user_id: int
    digest_frequency: str
    email_enabled: bool
    telegram_enabled: bool
    quiet_hours_start: int | None
    quiet_hours_end: int | None
    channels: list[ChannelInfo] = field(default_factory=list)


class NotificationChannel(Protocol):
    """Доставка отрендеренного сообщения на адрес канала."""

    @property
    def channel_type(self) -> ChannelType: ...

    async def send(self, address: str, message: NotificationMessage) -> None: ...


class NotificationsUnitOfWork(Protocol):
    async def __aenter__(self) -> NotificationsUnitOfWork: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...

    async def get_delivery_context(self, user_id: int) -> DeliveryContext | None: ...
    async def add_notification(self, notification: Notification) -> Notification: ...
    async def list_notifications(
        self, user_id: int, *, limit: int, offset: int
    ) -> list[Notification]: ...
    async def count_unread(self, user_id: int) -> int: ...
    async def mark_read(self, user_id: int, notification_id: int) -> bool: ...
    async def due_digest_user_ids(self, *, frequency: str) -> list[int]: ...
    async def set_email_digest_enabled(self, user_id: int, enabled: bool) -> None: ...


NotificationsUnitOfWorkFactory = Callable[[], NotificationsUnitOfWork]

__all__ = [
    "ChannelInfo",
    "DeliveryContext",
    "NotificationChannel",
    "NotificationMessage",
    "NotificationType",
    "NotificationsUnitOfWork",
    "NotificationsUnitOfWorkFactory",
]
