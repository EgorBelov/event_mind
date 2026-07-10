"""Unit: ResolveAccountByTelegram — резолв аккаунта по telegram chat_id."""
from __future__ import annotations

import pytest

from eventmind.application.accounts.use_cases import ResolveAccountByTelegram
from eventmind.domain.accounts.entities import UserChannel
from eventmind.domain.accounts.value_objects import ChannelType

from ._fakes import FakeStore, uow_factory


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


async def _add_channel(store: FakeStore, *, verified: bool, enabled: bool) -> None:
    async with uow_factory(store)() as uow:
        await uow.channels.add(
            UserChannel(
                user_id=7,
                type=ChannelType.TELEGRAM,
                address="555",
                verified=verified,
                enabled=enabled,
            )
        )
        await uow.commit()


async def test_resolves_verified_enabled_channel(store: FakeStore) -> None:
    await _add_channel(store, verified=True, enabled=True)
    assert await ResolveAccountByTelegram(uow_factory(store)).execute("555") == 7


async def test_unknown_chat_id_returns_none(store: FakeStore) -> None:
    assert await ResolveAccountByTelegram(uow_factory(store)).execute("000") is None


async def test_unverified_channel_returns_none(store: FakeStore) -> None:
    await _add_channel(store, verified=False, enabled=True)
    assert await ResolveAccountByTelegram(uow_factory(store)).execute("555") is None


async def test_disabled_channel_returns_none(store: FakeStore) -> None:
    await _add_channel(store, verified=True, enabled=False)
    assert await ResolveAccountByTelegram(uow_factory(store)).execute("555") is None
