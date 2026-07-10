"""Сид демо-данных. Запуск: `python -m eventmind.interfaces.cli.seed`.

Идемпотентен: повторный запуск не плодит дубли. В M1 создаёт подтверждённый
демо-аккаунт email+пароль с каналом email и настройками уведомлений.
"""
from __future__ import annotations

import asyncio

import structlog

from eventmind.config import get_settings
from eventmind.domain.accounts.entities import (
    NotificationPreference,
    User,
    UserChannel,
)
from eventmind.domain.accounts.value_objects import ChannelType
from eventmind.infrastructure.db.engine import create_engine, create_session_factory
from eventmind.infrastructure.db.uow import SqlAlchemyUnitOfWork
from eventmind.infrastructure.logging import configure_logging
from eventmind.infrastructure.security.password import Argon2PasswordHasher

_logger = structlog.get_logger("eventmind.seed")

DEMO_EMAIL = "demo@eventmind.local"
DEMO_PASSWORD = "demo12345"


async def seed() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    hasher = Argon2PasswordHasher()

    try:
        uow = SqlAlchemyUnitOfWork(session_factory)
        async with uow:
            if await uow.users.get_by_email(DEMO_EMAIL) is not None:
                _logger.info("seed_skip_exists", email=DEMO_EMAIL)
                return
            user = await uow.users.add(
                User(
                    email=DEMO_EMAIL,
                    password_hash=hasher.hash(DEMO_PASSWORD),
                    email_verified=True,
                )
            )
            assert user.id is not None
            await uow.channels.add(
                UserChannel(
                    user_id=user.id,
                    type=ChannelType.EMAIL,
                    address=DEMO_EMAIL,
                    verified=True,
                )
            )
            await uow.preferences.add(NotificationPreference(user_id=user.id))
            await uow.commit()
            _logger.info("seed_created", email=DEMO_EMAIL, password=DEMO_PASSWORD)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
