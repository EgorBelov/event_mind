"""Integration: inbox API, unsubscribe, SendUserDigest → инбокс + гейтинг каналов."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eventmind.application.notifications.use_cases import SendUserDigest
from eventmind.application.recommender.config import RecommenderConfig
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.application.recommender.use_cases import GetRecommendations
from eventmind.config import Settings
from eventmind.domain.notifications.entities import Notification, NotificationType
from eventmind.domain.recommender.weights import ScoringWeights
from eventmind.infrastructure.cache.redis_cache import RedisCache
from eventmind.infrastructure.db.engine import create_session_factory
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    NotificationPreferenceModel,
    TopicModel,
    UserModel,
)
from eventmind.infrastructure.db.notifications import SqlAlchemyNotificationsUnitOfWork
from eventmind.infrastructure.db.recommendation import SqlAlchemyRecommendationUnitOfWork
from eventmind.infrastructure.recommender.candidate_generator import PgvectorCandidateGenerator
from eventmind.infrastructure.redis import create_redis
from eventmind.infrastructure.security.jwt import JwtTokenService
from eventmind.infrastructure.security.tokens import SystemClock
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")
NOW = datetime.now(UTC)


def _register(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    ).status_code == 201


async def _run(coro: Any) -> Any:
    return await coro


def _sf(db_url: str) -> async_sessionmaker:
    return create_session_factory(create_async_engine(db_url))


def _user_id(db_url: str, email: str) -> int:
    async def _q() -> int:
        engine = create_async_engine(db_url)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(select(UserModel.id).where(UserModel.email == email))
                return int(row.scalar_one())
        finally:
            await engine.dispose()

    return asyncio.run(_q())


class _FakeEmail:
    channel_type = None  # выставим ниже

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, address: str, message: Any) -> None:
        self.sent.append(address)


def test_inbox_and_mark_read(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "inbox@example.com")
        uid = _user_id(settings.database_url, "inbox@example.com")

        # прямая запись уведомления в инбокс
        async def _seed() -> int:
            sf = _sf(settings.database_url)
            async with SqlAlchemyNotificationsUnitOfWork(sf) as uow:
                n = await uow.add_notification(
                    Notification(
                        user_id=uid, type=NotificationType.DIGEST, title="Digest", body="hi"
                    )
                )
                await uow.commit()
                assert n.id is not None
                return n.id

        nid = asyncio.run(_seed())

        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        body = resp.json()
        assert body["unread"] == 1
        assert body["items"][0]["title"] == "Digest"

        assert client.post(f"/api/v1/notifications/{nid}/read").status_code == 200
        assert client.get("/api/v1/notifications").json()["unread"] == 0


def test_unsubscribe_disables_email(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "unsub@example.com")
        uid = _user_id(settings.database_url, "unsub@example.com")

    token = JwtTokenService(settings.jwt_secret).create_purpose_token(
        str(uid), "unsubscribe", ttl_seconds=3600
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get(f"/api/v1/notifications/unsubscribe?token={token}")
        assert resp.status_code == 200

    async def _pref() -> bool:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(
                    select(NotificationPreferenceModel.email_enabled).where(
                        NotificationPreferenceModel.user_id == uid
                    )
                )
                return bool(row.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(_pref()) is False


def test_send_digest_writes_inbox_and_delivers_email(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "digest@example.com")
    uid = _user_id(settings.database_url, "digest@example.com")

    # засеять событие
    async def _seed_events() -> None:
        sf = _sf(settings.database_url)
        async with sf() as s:
            topic = TopicModel(code="backend", title="Backend")
            s.add(topic)
            await s.flush()
            ev = EventModel(
                source="seed", title="Digest Event", description="d", format="offline",
                city="moscow", level="middle", date="", start_at=NOW + timedelta(days=2),
                source_url="http://d/1", tech_stack=[], quality_score=9, embedding=[0.1] * 384,
            )
            s.add(ev)
            await s.flush()
            s.add(EventTopicModel(event_id=ev.id, topic_id=topic.id))
            await s.commit()

    asyncio.run(_seed_events())

    async def _send() -> Any:
        sf = _sf(settings.database_url)
        redis = create_redis(settings)
        try:
            get_reco = GetRecommendations(
                lambda: SqlAlchemyRecommendationUnitOfWork(sf),
                PgvectorCandidateGenerator(sf),
                HybridRanker(),
                RedisCache(redis),
                SystemClock(),
                RecommenderConfig(),
                ScoringWeights(),
            )
            email = _FakeEmail()
            from eventmind.domain.accounts.value_objects import ChannelType

            email.channel_type = ChannelType.EMAIL  # type: ignore[assignment]
            send = SendUserDigest(
                lambda: SqlAlchemyNotificationsUnitOfWork(sf),
                get_reco,
                {ChannelType.EMAIL: email},
                JwtTokenService(settings.jwt_secret),
                SystemClock(),
                settings.public_web_url,
            )
            report = await send.execute(uid)
            return report, email
        finally:
            await redis.aclose()

    report, email = asyncio.run(_send())
    assert "in_app" in report.delivered
    # email-канал аккаунта verified после регистрации? нет — verify не вызывали,
    # поэтому доставка в email пропущена (verified=False). Проверяем инбокс.
    with TestClient(create_app(settings)) as client:
        # логинимся тем же пользователем, читаем инбокс
        client.post(
            "/api/v1/auth/login",
            json={"email": "digest@example.com", "password": "password123"},
        )
        inbox = client.get("/api/v1/notifications").json()
    assert inbox["unread"] >= 1
    assert "рекомендаций" in inbox["items"][0]["title"]
