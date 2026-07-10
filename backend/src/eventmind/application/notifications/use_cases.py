"""Use-case'ы доставки: дайджест, планировщик, инбокс, unsubscribe.

Тот же ранкинг рекомендера питает все каналы; рендер — под канал. Выбор
каналов — по `NotificationPreference` + верификации (анти-абьюз). Внешние
каналы (email/telegram) шлются вне транзакции БД: сбой доставки не откатывает
запись in-app инбокса.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import jwt
import structlog

from eventmind.application.notifications.digest import build_digest_message
from eventmind.application.ports.notifications import (
    NotificationChannel,
    NotificationsUnitOfWorkFactory,
)
from eventmind.application.ports.queue import TaskQueue
from eventmind.application.ports.security import Clock, TokenService
from eventmind.application.recommender.use_cases import GetRecommendations
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.domain.notifications.entities import Notification, NotificationType

_logger = structlog.get_logger("eventmind.notifications")

SEND_DIGEST_TASK = "send_user_digest"
UNSUBSCRIBE_PURPOSE = "unsubscribe"
UNSUBSCRIBE_TTL_SECONDS = 90 * 24 * 3600
DIGEST_SIZE = 5


@dataclass(slots=True)
class DeliveryReport:
    user_id: int
    delivered: list[str] = field(default_factory=list)
    skipped: str | None = None


def in_quiet_hours(hour: int, start: int | None, end: int | None) -> bool:
    """Попадает ли час в тихие часы. Поддерживает переход через полночь (22..7)."""
    if start is None or end is None:
        return False
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class SendUserDigest:
    def __init__(
        self,
        uow_factory: NotificationsUnitOfWorkFactory,
        get_recommendations: GetRecommendations,
        channels: dict[ChannelType, NotificationChannel],
        token_service: TokenService,
        clock: Clock,
        public_web_url: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._get_recommendations = get_recommendations
        self._channels = channels
        self._token_service = token_service
        self._clock = clock
        self._public_web_url = public_web_url.rstrip("/")

    def _unsubscribe_url(self, user_id: int) -> str:
        token = self._token_service.create_purpose_token(
            str(user_id), UNSUBSCRIBE_PURPOSE, ttl_seconds=UNSUBSCRIBE_TTL_SECONDS
        )
        return f"{self._public_web_url}/api/v1/notifications/unsubscribe?token={token}"

    async def execute(self, user_id: int) -> DeliveryReport:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            ctx = await uow.get_delivery_context(user_id)
            if ctx is None or ctx.digest_frequency == "off":
                return DeliveryReport(user_id, skipped="disabled")
            if in_quiet_hours(now.hour, ctx.quiet_hours_start, ctx.quiet_hours_end):
                return DeliveryReport(user_id, skipped="quiet_hours")

            items = (await self._get_recommendations.execute(user_id))[:DIGEST_SIZE]
            if not items:
                return DeliveryReport(user_id, skipped="no_items")

            message = build_digest_message(items, unsubscribe_url=self._unsubscribe_url(user_id))
            # in-app инбокс — в транзакции.
            await uow.add_notification(
                Notification(
                    user_id=user_id,
                    type=NotificationType.DIGEST,
                    title=message.subject,
                    body=message.text,
                    payload={"events": message.items},
                )
            )
            await uow.commit()
            channels_snapshot = list(ctx.channels)
            email_on, tg_on = ctx.email_enabled, ctx.telegram_enabled

        report = DeliveryReport(user_id, delivered=["in_app"])
        # Внешние каналы — вне транзакции (сеть).
        for ch in channels_snapshot:
            if not (ch.verified and ch.enabled):
                continue
            if ch.type is ChannelType.EMAIL and not email_on:
                continue
            if ch.type is ChannelType.TELEGRAM and not tg_on:
                continue
            channel = self._channels.get(ch.type)
            if channel is None:
                continue
            try:
                await channel.send(ch.address, message)
            except Exception as exc:
                _logger.warning("delivery_failed", channel=ch.type.value, error=str(exc))
                continue
            report.delivered.append(ch.type.value)
        return report


class ScheduleDigests:
    """cron→queue: поставить дайджест каждому пользователю нужной частоты."""

    def __init__(
        self, uow_factory: NotificationsUnitOfWorkFactory, task_queue: TaskQueue
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = task_queue

    async def execute(self, *, frequency: str) -> int:
        async with self._uow_factory() as uow:
            user_ids = await uow.due_digest_user_ids(frequency=frequency)
        for user_id in user_ids:
            await self._queue.enqueue(SEND_DIGEST_TASK, user_id=user_id)
        return len(user_ids)


class ListInbox:
    def __init__(self, uow_factory: NotificationsUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, user_id: int, *, limit: int = 30, offset: int = 0
    ) -> tuple[list[Notification], int]:
        async with self._uow_factory() as uow:
            notifications = await uow.list_notifications(user_id, limit=limit, offset=offset)
            unread = await uow.count_unread(user_id)
        return notifications, unread


class MarkNotificationRead:
    def __init__(self, uow_factory: NotificationsUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, user_id: int, notification_id: int) -> bool:
        async with self._uow_factory() as uow:
            ok = await uow.mark_read(user_id, notification_id)
            await uow.commit()
        return ok


class Unsubscribe:
    """Отписка от email-дайджеста по токену из письма."""

    def __init__(
        self, uow_factory: NotificationsUnitOfWorkFactory, token_service: TokenService
    ) -> None:
        self._uow_factory = uow_factory
        self._token_service = token_service

    async def execute(self, token: str) -> bool:
        try:
            claims = self._token_service.decode(token)
        except jwt.InvalidTokenError:
            return False
        if claims.get("type") != UNSUBSCRIBE_PURPOSE:
            return False
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.isdigit():
            return False
        async with self._uow_factory() as uow:
            await uow.set_email_digest_enabled(int(subject), False)
            await uow.commit()
        return True
