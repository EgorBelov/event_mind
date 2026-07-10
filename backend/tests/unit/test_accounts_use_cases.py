"""Unit: use-case'ы аккаунтов на in-memory фейках (детерминизм, без БД)."""
from __future__ import annotations

import pytest

from eventmind.application.accounts.config import AccountsConfig
from eventmind.application.accounts.use_cases import (
    AuthenticateUser,
    ConfirmTelegramLink,
    CreateTelegramLinkToken,
    RegisterUser,
    RequestPasswordReset,
    ResetPassword,
    VerifyEmail,
)
from eventmind.domain.accounts.errors import (
    ChannelAlreadyLinked,
    EmailAlreadyRegistered,
    InvalidCredentials,
    TokenInvalidOrExpired,
)
from eventmind.domain.accounts.value_objects import ChannelType

from ._fakes import (
    FakePasswordHasher,
    FakeStore,
    FakeTaskQueue,
    FixedClock,
    SequentialTokenGenerator,
    uow_factory,
)

CONFIG = AccountsConfig()


@pytest.fixture
def ctx() -> dict[str, object]:
    store = FakeStore()
    return {
        "store": store,
        "uow": uow_factory(store),
        "hasher": FakePasswordHasher(),
        "tokens": SequentialTokenGenerator(),
        "clock": FixedClock(),
        "queue": FakeTaskQueue(),
    }


def _register_uc(ctx: dict[str, object]) -> RegisterUser:
    return RegisterUser(
        ctx["uow"], ctx["hasher"], ctx["tokens"], ctx["clock"], ctx["queue"], CONFIG  # type: ignore[arg-type]
    )


async def test_register_creates_account_channel_pref_token_and_event(
    ctx: dict[str, object],
) -> None:
    store: FakeStore = ctx["store"]  # type: ignore[assignment]
    queue: FakeTaskQueue = ctx["queue"]  # type: ignore[assignment]
    user = await _register_uc(ctx).execute(email="New@Ex.com", password="password123")

    assert user.id is not None
    assert user.email == "new@ex.com"  # нормализован
    # канал email + preferences созданы
    assert any(c.type is ChannelType.EMAIL for c in store.channels.values())
    assert user.id in store.prefs
    # событие UserRegistered ушло в outbox с сырым токеном
    assert len(store.outbox) == 1
    event_type, payload = store.outbox[0]
    assert event_type == "user.registered"
    assert payload["verification_token"] == "tok-1"
    # поставлена задача обработки outbox
    assert queue.enqueued == ["process_outbox"]


async def test_register_duplicate_email_rejected(ctx: dict[str, object]) -> None:
    await _register_uc(ctx).execute(email="a@b.com", password="password123")
    with pytest.raises(EmailAlreadyRegistered):
        await _register_uc(ctx).execute(email="A@B.com", password="password123")


async def test_verify_email_marks_verified_and_consumes_token(
    ctx: dict[str, object],
) -> None:
    store: FakeStore = ctx["store"]  # type: ignore[assignment]
    user = await _register_uc(ctx).execute(email="a@b.com", password="password123")
    verify = VerifyEmail(ctx["uow"], ctx["tokens"], ctx["clock"])  # type: ignore[arg-type]

    await verify.execute(raw_token="tok-1")
    assert store.users[user.id].email_verified is True  # type: ignore[index]
    channel = next(iter(store.channels.values()))
    assert channel.verified is True
    # повторное использование токена запрещено
    with pytest.raises(TokenInvalidOrExpired):
        await verify.execute(raw_token="tok-1")


async def test_verify_email_bad_token_rejected(ctx: dict[str, object]) -> None:
    verify = VerifyEmail(ctx["uow"], ctx["tokens"], ctx["clock"])  # type: ignore[arg-type]
    with pytest.raises(TokenInvalidOrExpired):
        await verify.execute(raw_token="does-not-exist")


async def test_authenticate_success_and_failures(ctx: dict[str, object]) -> None:
    await _register_uc(ctx).execute(email="a@b.com", password="password123")
    auth = AuthenticateUser(ctx["uow"], ctx["hasher"])  # type: ignore[arg-type]

    user = await auth.execute(email="a@b.com", password="password123")
    assert user.email == "a@b.com"
    with pytest.raises(InvalidCredentials):
        await auth.execute(email="a@b.com", password="wrong")
    with pytest.raises(InvalidCredentials):
        await auth.execute(email="ghost@b.com", password="password123")


async def test_password_reset_flow(ctx: dict[str, object]) -> None:
    store: FakeStore = ctx["store"]  # type: ignore[assignment]
    queue: FakeTaskQueue = ctx["queue"]  # type: ignore[assignment]
    await _register_uc(ctx).execute(email="a@b.com", password="password123")
    store.outbox.clear()
    queue.enqueued.clear()

    request = RequestPasswordReset(
        ctx["uow"], ctx["tokens"], ctx["clock"], ctx["queue"], CONFIG  # type: ignore[arg-type]
    )
    await request.execute(email="a@b.com")
    assert store.outbox[0][0] == "password.reset_requested"
    reset_token = store.outbox[0][1]["reset_token"]
    assert queue.enqueued == ["process_outbox"]

    reset = ResetPassword(ctx["uow"], ctx["tokens"], ctx["hasher"], ctx["clock"])  # type: ignore[arg-type]
    await reset.execute(raw_token=str(reset_token), new_password="new-password-1")

    auth = AuthenticateUser(ctx["uow"], ctx["hasher"])  # type: ignore[arg-type]
    assert await auth.execute(email="a@b.com", password="new-password-1")


async def test_password_reset_unknown_email_is_silent(ctx: dict[str, object]) -> None:
    store: FakeStore = ctx["store"]  # type: ignore[assignment]
    queue: FakeTaskQueue = ctx["queue"]  # type: ignore[assignment]
    request = RequestPasswordReset(
        ctx["uow"], ctx["tokens"], ctx["clock"], ctx["queue"], CONFIG  # type: ignore[arg-type]
    )
    await request.execute(email="ghost@b.com")
    assert store.outbox == []  # ничего не создано
    assert queue.enqueued == []  # ничего не поставлено (анти-энумерация)


async def test_telegram_link_and_confirm(ctx: dict[str, object]) -> None:
    store: FakeStore = ctx["store"]  # type: ignore[assignment]
    user = await _register_uc(ctx).execute(email="a@b.com", password="password123")

    create = CreateTelegramLinkToken(ctx["uow"], ctx["tokens"], ctx["clock"], CONFIG)  # type: ignore[arg-type]
    raw = await create.execute(user_id=user.id)  # type: ignore[arg-type]

    confirm = ConfirmTelegramLink(ctx["uow"], ctx["tokens"], ctx["clock"])  # type: ignore[arg-type]
    linked_user_id = await confirm.execute(raw_token=raw, chat_id="99887766")
    assert linked_user_id == user.id

    channel = next(c for c in store.channels.values() if c.type is ChannelType.TELEGRAM)
    assert channel.address == "99887766" and channel.verified is True
    assert store.prefs[user.id].telegram_enabled is True  # type: ignore[index]


async def test_telegram_confirm_chat_linked_to_other_user_rejected(
    ctx: dict[str, object],
) -> None:
    u1 = await _register_uc(ctx).execute(email="a@b.com", password="password123")
    u2 = await _register_uc(ctx).execute(email="c@d.com", password="password123")

    create = CreateTelegramLinkToken(ctx["uow"], ctx["tokens"], ctx["clock"], CONFIG)  # type: ignore[arg-type]
    confirm = ConfirmTelegramLink(ctx["uow"], ctx["tokens"], ctx["clock"])  # type: ignore[arg-type]

    raw1 = await create.execute(user_id=u1.id)  # type: ignore[arg-type]
    await confirm.execute(raw_token=raw1, chat_id="55")

    raw2 = await create.execute(user_id=u2.id)  # type: ignore[arg-type]
    with pytest.raises(ChannelAlreadyLinked):
        await confirm.execute(raw_token=raw2, chat_id="55")


async def test_telegram_confirm_expired_token_rejected(ctx: dict[str, object]) -> None:
    clock: FixedClock = ctx["clock"]  # type: ignore[assignment]
    user = await _register_uc(ctx).execute(email="a@b.com", password="password123")
    create = CreateTelegramLinkToken(ctx["uow"], ctx["tokens"], ctx["clock"], CONFIG)  # type: ignore[arg-type]
    raw = await create.execute(user_id=user.id)  # type: ignore[arg-type]

    clock.advance(CONFIG.telegram_link_ttl_seconds + 1)
    confirm = ConfirmTelegramLink(ctx["uow"], ctx["tokens"], ctx["clock"])  # type: ignore[arg-type]
    with pytest.raises(TokenInvalidOrExpired):
        await confirm.execute(raw_token=raw, chat_id="55")
