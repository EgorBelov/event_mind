"""Unit: доменные VO/сущности аккаунтов."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eventmind.domain.accounts.entities import OneTimeToken, User
from eventmind.domain.accounts.errors import AccountInactive
from eventmind.domain.accounts.value_objects import Email


def test_email_normalizes_case_and_whitespace() -> None:
    assert str(Email("  User@Example.COM ")) == "user@example.com"


@pytest.mark.parametrize("bad", ["", "no-at", "a@b", "a@b@c.com", "spaces @x.com"])
def test_email_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        Email(bad)


def test_user_inactive_cannot_login() -> None:
    user = User(email="a@b.com", password_hash="x", is_active=False)
    with pytest.raises(AccountInactive):
        user.ensure_can_login()


def test_one_time_token_usable_and_consume() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    token = OneTimeToken(
        user_id=1, purpose="x", token_hash="h", expires_at=now + timedelta(hours=1)
    )
    assert token.is_usable(now=now)
    token.consume(now=now)
    assert not token.is_usable(now=now)  # уже использован


def test_one_time_token_expired_not_usable() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    token = OneTimeToken(
        user_id=1, purpose="x", token_hash="h", expires_at=now - timedelta(seconds=1)
    )
    assert not token.is_usable(now=now)
