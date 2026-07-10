"""In-memory фейки портов для unit-тестов use-case'ов (без БД/Redis/SMTP)."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from eventmind.domain.accounts.entities import (
    NotificationPreference,
    OneTimeToken,
    User,
    UserChannel,
)
from eventmind.domain.accounts.events import DomainEvent
from eventmind.domain.accounts.value_objects import ChannelType


@dataclass
class FakeStore:
    """Общее in-memory хранилище, разделяемое всеми UoW в тесте."""

    users: dict[int, User] = field(default_factory=dict)
    channels: dict[int, UserChannel] = field(default_factory=dict)
    prefs: dict[int, NotificationPreference] = field(default_factory=dict)
    tokens: dict[int, OneTimeToken] = field(default_factory=dict)
    outbox: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def next_id(self) -> int:
        return next(self._ids)


class _Users:
    def __init__(self, store: FakeStore) -> None:
        self._s = store

    async def add(self, user: User) -> User:
        user.id = self._s.next_id()
        user.created_at = datetime.now(UTC)
        self._s.users[user.id] = user
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._s.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._s.users.values() if u.email == email), None)

    async def update(self, user: User) -> None:
        assert user.id is not None
        self._s.users[user.id] = user


class _Channels:
    def __init__(self, store: FakeStore) -> None:
        self._s = store

    async def add(self, channel: UserChannel) -> UserChannel:
        channel.id = self._s.next_id()
        self._s.channels[channel.id] = channel
        return channel

    async def get_by_user_and_type(
        self, user_id: int, channel_type: ChannelType
    ) -> UserChannel | None:
        return next(
            (c for c in self._s.channels.values()
             if c.user_id == user_id and c.type is channel_type),
            None,
        )

    async def get_by_type_and_address(
        self, channel_type: ChannelType, address: str
    ) -> UserChannel | None:
        return next(
            (c for c in self._s.channels.values()
             if c.type is channel_type and c.address == address),
            None,
        )

    async def update(self, channel: UserChannel) -> None:
        assert channel.id is not None
        self._s.channels[channel.id] = channel


class _Prefs:
    def __init__(self, store: FakeStore) -> None:
        self._s = store

    async def add(self, pref: NotificationPreference) -> NotificationPreference:
        pref.id = self._s.next_id()
        self._s.prefs[pref.user_id] = pref
        return pref

    async def get_by_user(self, user_id: int) -> NotificationPreference | None:
        return self._s.prefs.get(user_id)

    async def update(self, pref: NotificationPreference) -> None:
        self._s.prefs[pref.user_id] = pref


class _Tokens:
    def __init__(self, store: FakeStore) -> None:
        self._s = store

    async def add(self, token: OneTimeToken) -> OneTimeToken:
        token.id = self._s.next_id()
        self._s.tokens[token.id] = token
        return token

    async def get_by_hash(self, purpose: str, token_hash: str) -> OneTimeToken | None:
        return next(
            (t for t in self._s.tokens.values()
             if t.purpose == purpose and t.token_hash == token_hash),
            None,
        )

    async def update(self, token: OneTimeToken) -> None:
        assert token.id is not None
        self._s.tokens[token.id] = token


class FakeUnitOfWork:
    def __init__(self, store: FakeStore) -> None:
        self._s = store
        self._events: list[DomainEvent] = []
        self.users = _Users(store)
        self.channels = _Channels(store)
        self.preferences = _Prefs(store)
        self.tokens = _Tokens(store)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def add_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    async def commit(self) -> None:
        for event in self._events:
            self._s.outbox.append((event.event_type, event.payload()))
        self._events = []

    async def rollback(self) -> None:
        self._events = []


def uow_factory(store: FakeStore):
    return lambda: FakeUnitOfWork(store)


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, task: str, **kwargs: object) -> None:
        self.enqueued.append(task)


class FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hash::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hash::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class SequentialTokenGenerator:
    """Детерминированный генератор: raw = 'tok-N', hash = 'h::tok-N'."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def generate(self) -> tuple[str, str]:
        raw = f"tok-{next(self._counter)}"
        return raw, self.hash(raw)

    def hash(self, raw: str) -> str:
        return f"h::{raw}"


class FixedClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + timedelta(seconds=seconds)
