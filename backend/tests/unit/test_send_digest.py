"""Unit: SendUserDigest — гейтинг каналов, тихие часы, инбокс; Unsubscribe-токен."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jwt
import pytest

from eventmind.application.notifications.use_cases import (
    SendUserDigest,
    Unsubscribe,
)
from eventmind.application.ports.notifications import ChannelInfo, DeliveryContext
from eventmind.application.recommender.use_cases import RecommendationItem
from eventmind.domain.accounts.value_objects import ChannelType


def _item() -> RecommendationItem:
    return RecommendationItem(
        event_id=1, title="E1", description="d", date="", city="moscow",
        format="offline", event_type="meetup", source_url="http://e/1",
        score=1.0, topics=["backend"],
    )


class FakeNotifUoW:
    def __init__(self, ctx: DeliveryContext | None) -> None:
        self._ctx = ctx
        self.added: list[Any] = []
        self.email_disabled_for: list[int] = []

    async def __aenter__(self) -> FakeNotifUoW:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def get_delivery_context(self, user_id: int) -> DeliveryContext | None:
        return self._ctx

    async def add_notification(self, notification: Any) -> Any:
        self.added.append(notification)
        return notification

    async def set_email_digest_enabled(self, user_id: int, enabled: bool) -> None:
        if not enabled:
            self.email_disabled_for.append(user_id)


class FakeRecommendations:
    def __init__(self, items: list[RecommendationItem]) -> None:
        self._items = items

    async def execute(self, user_id: int) -> list[RecommendationItem]:
        return self._items


class FakeChannel:
    def __init__(self, ctype: ChannelType, *, fail: bool = False) -> None:
        self.channel_type = ctype
        self.fail = fail
        self.sent: list[str] = []

    async def send(self, address: str, message: Any) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append(address)


class FakeTokens:
    def create_purpose_token(self, subject: str, purpose: str, *, ttl_seconds: int) -> str:
        return f"tok:{subject}:{purpose}"

    def decode(self, token: str) -> dict[str, object]:
        if token == "bad":
            raise jwt.InvalidTokenError("bad")
        _, sub, purpose = token.split(":")
        return {"sub": sub, "type": purpose}


class FixedClock:
    def __init__(self, hour: int) -> None:
        self._hour = hour

    def now(self) -> datetime:
        return datetime(2026, 7, 10, self._hour, 0, tzinfo=UTC)


def _ctx(**kw: Any) -> DeliveryContext:
    base: dict[str, Any] = {
        "user_id": 1, "digest_frequency": "daily", "email_enabled": True,
        "telegram_enabled": False, "quiet_hours_start": None, "quiet_hours_end": None,
        "channels": [ChannelInfo(ChannelType.EMAIL, "u@e.com", verified=True, enabled=True)],
    }
    base.update(kw)
    return DeliveryContext(**base)


def _digest(
    uow: FakeNotifUoW, channels: dict[ChannelType, Any], *, hour: int = 12
) -> SendUserDigest:
    return SendUserDigest(
        lambda: uow, FakeRecommendations([_item()]), channels, FakeTokens(),
        FixedClock(hour), "http://web",
    )


async def test_delivers_inapp_and_email() -> None:
    uow = FakeNotifUoW(_ctx())
    email = FakeChannel(ChannelType.EMAIL)
    report = await _digest(uow, {ChannelType.EMAIL: email}).execute(1)
    assert "in_app" in report.delivered
    assert "email" in report.delivered
    assert email.sent == ["u@e.com"]
    assert len(uow.added) == 1  # запись в инбокс


async def test_telegram_skipped_when_pref_disabled() -> None:
    ctx = _ctx(
        telegram_enabled=False,
        channels=[ChannelInfo(ChannelType.TELEGRAM, "999", verified=True, enabled=True)],
    )
    uow = FakeNotifUoW(ctx)
    tg = FakeChannel(ChannelType.TELEGRAM)
    report = await _digest(uow, {ChannelType.TELEGRAM: tg}).execute(1)
    assert report.delivered == ["in_app"]
    assert tg.sent == []


async def test_unverified_channel_skipped() -> None:
    ctx = _ctx(channels=[ChannelInfo(ChannelType.EMAIL, "u@e.com", verified=False, enabled=True)])
    uow = FakeNotifUoW(ctx)
    email = FakeChannel(ChannelType.EMAIL)
    report = await _digest(uow, {ChannelType.EMAIL: email}).execute(1)
    assert "email" not in report.delivered
    assert email.sent == []


async def test_channel_failure_does_not_break() -> None:
    uow = FakeNotifUoW(_ctx())
    email = FakeChannel(ChannelType.EMAIL, fail=True)
    report = await _digest(uow, {ChannelType.EMAIL: email}).execute(1)
    assert report.delivered == ["in_app"]  # email упал, но инбокс записан


async def test_skipped_in_quiet_hours() -> None:
    uow = FakeNotifUoW(_ctx(quiet_hours_start=22, quiet_hours_end=7))
    report = await _digest(uow, {}, hour=3).execute(1)
    assert report.skipped == "quiet_hours"
    assert uow.added == []


async def test_skipped_when_digest_off() -> None:
    uow = FakeNotifUoW(_ctx(digest_frequency="off"))
    report = await _digest(uow, {}).execute(1)
    assert report.skipped == "disabled"


@pytest.mark.parametrize("token,expected", [("tok:5:unsubscribe", True), ("bad", False)])
async def test_unsubscribe(token: str, expected: bool) -> None:
    uow = FakeNotifUoW(_ctx())
    ok = await Unsubscribe(lambda: uow, FakeTokens()).execute(token)
    assert ok is expected
    if expected:
        assert uow.email_disabled_for == [5]
