"""Integration: транзакционный outbox + диспетчеризация OutboxProcessor'ом.

Проверяет ключевую гарантию M1: событие и агрегат пишутся атомарно, а релей
доставляет его в обработчик и помечает processed.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from eventmind.application.accounts.email_handlers import make_user_registered_handler
from eventmind.application.outbox.processor import OutboxProcessor
from eventmind.application.ports.email import EmailMessage
from eventmind.domain.accounts.entities import User
from eventmind.domain.accounts.events import UserRegistered
from eventmind.infrastructure.db.models import OutboxModel, UserModel
from eventmind.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from eventmind.infrastructure.db.uow import SqlAlchemyUnitOfWork
from eventmind.infrastructure.email.renderer import Jinja2EmailRenderer

pytestmark = pytest.mark.usefixtures("clean_tables")


class _RecordingChannel:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


async def _count(session_factory: async_sessionmaker, model: type) -> int:
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def test_commit_writes_user_and_outbox_atomically(
    session_factory: async_sessionmaker,
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    async with uow:
        user = await uow.users.add(User(email="a@b.com", password_hash="x"))
        assert user.id is not None
        uow.add_event(
            UserRegistered(user_id=user.id, email="a@b.com", verification_token="raw-1")
        )
        await uow.commit()

    assert await _count(session_factory, UserModel) == 1
    assert await _count(session_factory, OutboxModel) == 1


async def test_rollback_on_error_leaves_nothing(
    session_factory: async_sessionmaker,
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with pytest.raises(RuntimeError):
        async with uow:
            await uow.users.add(User(email="x@y.com", password_hash="x"))
            uow.add_event(
                UserRegistered(user_id=1, email="x@y.com", verification_token="raw")
            )
            raise RuntimeError("boom before commit")

    assert await _count(session_factory, UserModel) == 0
    assert await _count(session_factory, OutboxModel) == 0


async def test_processor_dispatches_and_marks_processed(
    settings, session_factory: async_sessionmaker
) -> None:
    # засеять событие через UoW
    uow = SqlAlchemyUnitOfWork(session_factory)
    async with uow:
        user = await uow.users.add(User(email="proc@b.com", password_hash="x"))
        uow.add_event(
            UserRegistered(
                user_id=user.id, email="proc@b.com", verification_token="raw-xyz"  # type: ignore[arg-type]
            )
        )
        await uow.commit()

    channel = _RecordingChannel()
    renderer = Jinja2EmailRenderer(settings.public_web_url)
    store = SqlAlchemyOutboxStore(session_factory)
    handler = make_user_registered_handler(channel, renderer, settings.public_web_url)
    processor = OutboxProcessor(store, {"user.registered": handler})

    processed = await processor.process_pending()
    assert processed == 1
    assert len(channel.sent) == 1
    msg = channel.sent[0]
    assert msg.to == "proc@b.com"
    assert "raw-xyz" in msg.html  # ссылка верификации содержит токен

    # повторный прогон — уже нечего обрабатывать (идемпотентность пометки)
    assert await processor.process_pending() == 0
