"""`SqlAlchemyNotificationsUnitOfWork` — доставка/инбокс/планировщик/unsubscribe."""
from __future__ import annotations

from types import TracebackType

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.notifications import ChannelInfo, DeliveryContext
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.domain.notifications.entities import Notification, NotificationType
from eventmind.infrastructure.db.models import (
    NotificationModel,
    NotificationPreferenceModel,
    UserChannelModel,
)


def _to_entity(m: NotificationModel) -> Notification:
    return Notification(
        id=m.id,
        user_id=m.user_id,
        type=NotificationType(m.type),
        title=m.title,
        body=m.body,
        payload=dict(m.payload),
        read=m.read,
        created_at=m.created_at,
    )


class SqlAlchemyNotificationsUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyNotificationsUnitOfWork:
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    @property
    def _s(self) -> AsyncSession:
        assert self._session is not None
        return self._session

    async def commit(self) -> None:
        await self._s.commit()

    async def get_delivery_context(self, user_id: int) -> DeliveryContext | None:
        pref = (
            await self._s.execute(
                select(NotificationPreferenceModel).where(
                    NotificationPreferenceModel.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if pref is None:
            return None
        channel_rows = (
            await self._s.execute(
                select(UserChannelModel).where(UserChannelModel.user_id == user_id)
            )
        ).scalars().all()
        channels = [
            ChannelInfo(
                type=ChannelType(c.type),
                address=c.address,
                verified=c.verified,
                enabled=c.enabled,
            )
            for c in channel_rows
        ]
        return DeliveryContext(
            user_id=user_id,
            digest_frequency=pref.digest_frequency,
            email_enabled=pref.email_enabled,
            telegram_enabled=pref.telegram_enabled,
            quiet_hours_start=pref.quiet_hours_start,
            quiet_hours_end=pref.quiet_hours_end,
            channels=channels,
        )

    async def add_notification(self, notification: Notification) -> Notification:
        model = NotificationModel(
            user_id=notification.user_id,
            type=notification.type.value,
            title=notification.title,
            body=notification.body,
            payload=notification.payload,
            read=notification.read,
        )
        self._s.add(model)
        await self._s.flush()
        notification.id = model.id
        notification.created_at = model.created_at
        return notification

    async def list_notifications(
        self, user_id: int, *, limit: int, offset: int
    ) -> list[Notification]:
        rows = await self._s.execute(
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id)
            .order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_entity(m) for m in rows.scalars().all()]

    async def count_unread(self, user_id: int) -> int:
        result = await self._s.execute(
            select(func.count())
            .select_from(NotificationModel)
            .where(NotificationModel.user_id == user_id, NotificationModel.read.is_(False))
        )
        return int(result.scalar_one())

    async def mark_read(self, user_id: int, notification_id: int) -> bool:
        result = await self._s.execute(
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.user_id == user_id,
            )
            .values(read=True)
        )
        return bool(getattr(result, "rowcount", 0))

    async def due_digest_user_ids(self, *, frequency: str) -> list[int]:
        rows = await self._s.execute(
            select(NotificationPreferenceModel.user_id).where(
                NotificationPreferenceModel.digest_frequency == frequency
            )
        )
        return [uid for (uid,) in rows.all()]

    async def set_email_digest_enabled(self, user_id: int, enabled: bool) -> None:
        await self._s.execute(
            update(NotificationPreferenceModel)
            .where(NotificationPreferenceModel.user_id == user_id)
            .values(email_enabled=enabled)
        )
