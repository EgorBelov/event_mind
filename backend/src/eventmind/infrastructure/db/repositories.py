"""async-SQLAlchemy-реализации репозиториев (порты `application.ports.repositories`).

Работают в рамках сессии текущего `UnitOfWork`. Маппинг доменные↔ORM —
явные функции ниже; домен ORM не видит.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventmind.domain.accounts.entities import (
    NotificationPreference,
    OneTimeToken,
    User,
    UserChannel,
)
from eventmind.domain.accounts.value_objects import ChannelType, DigestFrequency
from eventmind.infrastructure.db.models import (
    NotificationPreferenceModel,
    OneTimeTokenModel,
    UserChannelModel,
    UserModel,
)


# ── мапперы ──────────────────────────────────────────────────────────────────
def _user_to_entity(m: UserModel) -> User:
    return User(
        id=m.id,
        email=m.email,
        password_hash=m.password_hash,
        email_verified=m.email_verified,
        is_active=m.is_active,
        oauth_provider=m.oauth_provider,
        oauth_sub=m.oauth_sub,
        created_at=m.created_at,
    )


def _channel_to_entity(m: UserChannelModel) -> UserChannel:
    return UserChannel(
        id=m.id,
        user_id=m.user_id,
        type=ChannelType(m.type),
        address=m.address,
        verified=m.verified,
        enabled=m.enabled,
        created_at=m.created_at,
    )


def _pref_to_entity(m: NotificationPreferenceModel) -> NotificationPreference:
    return NotificationPreference(
        id=m.id,
        user_id=m.user_id,
        digest_frequency=DigestFrequency(m.digest_frequency),
        email_enabled=m.email_enabled,
        telegram_enabled=m.telegram_enabled,
        quiet_hours_start=m.quiet_hours_start,
        quiet_hours_end=m.quiet_hours_end,
    )


def _token_to_entity(m: OneTimeTokenModel) -> OneTimeToken:
    return OneTimeToken(
        id=m.id,
        user_id=m.user_id,
        purpose=m.purpose,
        token_hash=m.token_hash,
        expires_at=m.expires_at,
        consumed_at=m.consumed_at,
        payload=dict(m.payload),
        created_at=m.created_at,
    )


# ── репозитории ──────────────────────────────────────────────────────────────
class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        model = UserModel(
            email=user.email,
            password_hash=user.password_hash,
            email_verified=user.email_verified,
            is_active=user.is_active,
            oauth_provider=user.oauth_provider,
            oauth_sub=user.oauth_sub,
        )
        self._session.add(model)
        await self._session.flush()
        user.id = model.id
        user.created_at = model.created_at
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _user_to_entity(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        model = result.scalar_one_or_none()
        return _user_to_entity(model) if model else None

    async def update(self, user: User) -> None:
        assert user.id is not None
        model = await self._session.get(UserModel, user.id)
        if model is None:
            return
        model.email = user.email
        model.password_hash = user.password_hash
        model.email_verified = user.email_verified
        model.is_active = user.is_active
        model.oauth_provider = user.oauth_provider
        model.oauth_sub = user.oauth_sub


class SqlAlchemyUserChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, channel: UserChannel) -> UserChannel:
        model = UserChannelModel(
            user_id=channel.user_id,
            type=channel.type.value,
            address=channel.address,
            verified=channel.verified,
            enabled=channel.enabled,
        )
        self._session.add(model)
        await self._session.flush()
        channel.id = model.id
        channel.created_at = model.created_at
        return channel

    async def get_by_user_and_type(
        self, user_id: int, channel_type: ChannelType
    ) -> UserChannel | None:
        result = await self._session.execute(
            select(UserChannelModel).where(
                UserChannelModel.user_id == user_id,
                UserChannelModel.type == channel_type.value,
            )
        )
        model = result.scalar_one_or_none()
        return _channel_to_entity(model) if model else None

    async def get_by_type_and_address(
        self, channel_type: ChannelType, address: str
    ) -> UserChannel | None:
        result = await self._session.execute(
            select(UserChannelModel).where(
                UserChannelModel.type == channel_type.value,
                UserChannelModel.address == address,
            )
        )
        model = result.scalar_one_or_none()
        return _channel_to_entity(model) if model else None

    async def update(self, channel: UserChannel) -> None:
        assert channel.id is not None
        model = await self._session.get(UserChannelModel, channel.id)
        if model is None:
            return
        model.address = channel.address
        model.verified = channel.verified
        model.enabled = channel.enabled


class SqlAlchemyNotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, pref: NotificationPreference) -> NotificationPreference:
        model = NotificationPreferenceModel(
            user_id=pref.user_id,
            digest_frequency=pref.digest_frequency.value,
            email_enabled=pref.email_enabled,
            telegram_enabled=pref.telegram_enabled,
            quiet_hours_start=pref.quiet_hours_start,
            quiet_hours_end=pref.quiet_hours_end,
        )
        self._session.add(model)
        await self._session.flush()
        pref.id = model.id
        return pref

    async def get_by_user(self, user_id: int) -> NotificationPreference | None:
        result = await self._session.execute(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user_id
            )
        )
        model = result.scalar_one_or_none()
        return _pref_to_entity(model) if model else None

    async def update(self, pref: NotificationPreference) -> None:
        assert pref.id is not None
        model = await self._session.get(NotificationPreferenceModel, pref.id)
        if model is None:
            return
        model.digest_frequency = pref.digest_frequency.value
        model.email_enabled = pref.email_enabled
        model.telegram_enabled = pref.telegram_enabled
        model.quiet_hours_start = pref.quiet_hours_start
        model.quiet_hours_end = pref.quiet_hours_end


class SqlAlchemyTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: OneTimeToken) -> OneTimeToken:
        model = OneTimeTokenModel(
            user_id=token.user_id,
            purpose=token.purpose,
            token_hash=token.token_hash,
            expires_at=token.expires_at,
            consumed_at=token.consumed_at,
            payload=token.payload,
        )
        self._session.add(model)
        await self._session.flush()
        token.id = model.id
        token.created_at = model.created_at
        return token

    async def get_by_hash(self, purpose: str, token_hash: str) -> OneTimeToken | None:
        result = await self._session.execute(
            select(OneTimeTokenModel).where(
                OneTimeTokenModel.purpose == purpose,
                OneTimeTokenModel.token_hash == token_hash,
            )
        )
        model = result.scalar_one_or_none()
        return _token_to_entity(model) if model else None

    async def update(self, token: OneTimeToken) -> None:
        assert token.id is not None
        model = await self._session.get(OneTimeTokenModel, token.id)
        if model is None:
            return
        model.consumed_at = token.consumed_at
        model.payload = token.payload
