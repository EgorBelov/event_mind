"""Unit: M6.2 — профиль (город/формат), настройки уведомлений, Google-вход.

Проверяем use-case'ы `UpdateProfile`, `UpdatePreferences`, `AuthenticateWithGoogle`
на in-memory фейках. `GoogleTokenVerifier` подменяется фейком (без сети).
"""
from __future__ import annotations

import pytest

from eventmind.application.accounts.config import AccountsConfig
from eventmind.application.accounts.use_cases import (
    AuthenticateWithGoogle,
    RegisterUser,
    UpdatePreferences,
    UpdateProfile,
)
from eventmind.application.ports.oauth import GoogleIdentity
from eventmind.domain.accounts.errors import InvalidCredentials, UserNotFound
from eventmind.domain.accounts.value_objects import ChannelType, DigestFrequency

from ._fakes import (
    FakePasswordHasher,
    FakeStore,
    FakeTaskQueue,
    FixedClock,
    SequentialTokenGenerator,
    uow_factory,
)

CONFIG = AccountsConfig()


class FakeGoogleVerifier:
    def __init__(self, identity: GoogleIdentity | None) -> None:
        self._identity = identity

    async def verify(self, id_token: str) -> GoogleIdentity | None:
        return self._identity


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


async def _register(store: FakeStore, email: str = "user@ex.com") -> int:
    uc = RegisterUser(
        uow_factory(store),
        FakePasswordHasher(),
        SequentialTokenGenerator(),
        FixedClock(),
        FakeTaskQueue(),
        CONFIG,
    )
    user = await uc.execute(email=email, password="password123")
    assert user.id is not None
    return user.id


# ── UpdateProfile ────────────────────────────────────────────────────────────
async def test_update_profile_canonicalizes_city(store: FakeStore) -> None:
    uid = await _register(store)
    uc = UpdateProfile(uow_factory(store))
    user = await uc.execute(uid, city="Piter", preferred_format="online")
    assert user.city == "spb"
    assert user.preferred_format == "online"
    assert store.users[uid].city == "spb"


async def test_update_profile_empty_strings_clear_fields(store: FakeStore) -> None:
    uid = await _register(store)
    uc = UpdateProfile(uow_factory(store))
    user = await uc.execute(uid, city="", preferred_format="")
    assert user.city is None
    assert user.preferred_format is None


async def test_update_profile_none_leaves_unchanged(store: FakeStore) -> None:
    uid = await _register(store)
    await UpdateProfile(uow_factory(store)).execute(
        uid, city="moscow", preferred_format="offline"
    )
    user = await UpdateProfile(uow_factory(store)).execute(
        uid, city=None, preferred_format=None
    )
    assert user.city == "moscow"
    assert user.preferred_format == "offline"


async def test_update_profile_unknown_user(store: FakeStore) -> None:
    with pytest.raises(UserNotFound):
        await UpdateProfile(uow_factory(store)).execute(999, city="x", preferred_format=None)


# ── UpdatePreferences ────────────────────────────────────────────────────────
async def test_update_preferences_changes_frequency_and_channels(store: FakeStore) -> None:
    uid = await _register(store)
    uc = UpdatePreferences(uow_factory(store))
    pref = await uc.execute(
        uid,
        digest_frequency="weekly",
        email_enabled=False,
        telegram_enabled=True,
        quiet_hours_start=23,
        quiet_hours_end=7,
    )
    assert pref.digest_frequency is DigestFrequency.WEEKLY
    assert pref.email_enabled is False
    assert pref.telegram_enabled is True
    assert pref.quiet_hours_start == 23
    assert pref.quiet_hours_end == 7


async def test_update_preferences_partial_leaves_rest(store: FakeStore) -> None:
    uid = await _register(store)
    pref = await UpdatePreferences(uow_factory(store)).execute(uid, digest_frequency="off")
    assert pref.digest_frequency is DigestFrequency.OFF
    # email_enabled по умолчанию True — не трогали.
    assert pref.email_enabled is True


async def test_update_preferences_missing_pref(store: FakeStore) -> None:
    with pytest.raises(UserNotFound):
        await UpdatePreferences(uow_factory(store)).execute(999, digest_frequency="daily")


# ── AuthenticateWithGoogle ───────────────────────────────────────────────────
async def test_google_creates_new_verified_account(store: FakeStore) -> None:
    verifier = FakeGoogleVerifier(GoogleIdentity(email="New@Gmail.com", sub="g-123"))
    user = await AuthenticateWithGoogle(uow_factory(store), verifier).execute("tok")
    assert user.id is not None
    assert user.email == "new@gmail.com"
    assert user.email_verified is True
    assert user.oauth_provider == "google"
    assert user.oauth_sub == "g-123"
    assert user.password_hash is None
    # email-канал создан и verified, prefs заведены
    channel = store.channels[next(iter(store.channels))]
    assert channel.type is ChannelType.EMAIL
    assert channel.verified is True
    assert store.prefs[user.id] is not None


async def test_google_links_existing_password_account(store: FakeStore) -> None:
    uid = await _register(store, email="user@ex.com")
    verifier = FakeGoogleVerifier(GoogleIdentity(email="user@ex.com", sub="g-999"))
    user = await AuthenticateWithGoogle(uow_factory(store), verifier).execute("tok")
    assert user.id == uid
    assert user.oauth_provider == "google"
    assert user.oauth_sub == "g-999"
    # существующий пароль не затёрт
    assert store.users[uid].password_hash is not None


async def test_google_invalid_token_raises(store: FakeStore) -> None:
    verifier = FakeGoogleVerifier(None)
    with pytest.raises(InvalidCredentials):
        await AuthenticateWithGoogle(uow_factory(store), verifier).execute("bad")


async def test_google_second_login_does_not_duplicate(store: FakeStore) -> None:
    verifier = FakeGoogleVerifier(GoogleIdentity(email="dup@ex.com", sub="g-1"))
    uc = AuthenticateWithGoogle(uow_factory(store), verifier)
    first = await uc.execute("tok")
    second = await uc.execute("tok")
    assert first.id == second.id
    assert len(store.users) == 1
