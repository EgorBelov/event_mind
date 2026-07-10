"""Integration: /recommendations (read-only) + /interactions (online-обучение) на pgvector."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from eventmind.config import Settings
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    InteractionModel,
    TopicModel,
    UserTopicStatModel,
)
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")

NOW = datetime.now(UTC)
VEC = [0.1] * 384


def _seed_events(db_url: str) -> list[int]:
    """Засеять topic backend + 3 события (разное quality) с эмбеддингами."""

    async def _run() -> list[int]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = create_async_engine(db_url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        ids: list[int] = []
        async with sf() as s:
            topic = TopicModel(code="backend", title="Backend")
            s.add(topic)
            await s.flush()
            for i, q in enumerate([9, 5, 2], start=1):
                ev = EventModel(
                    source="seed", title=f"Event {i}", description="desc",
                    format="offline", city="moscow", level="middle", date="",
                    start_at=NOW + timedelta(days=i), source_url=f"http://s/{i}",
                    tech_stack=[], quality_score=q, embedding=VEC,
                )
                s.add(ev)
                await s.flush()
                s.add(EventTopicModel(event_id=ev.id, topic_id=topic.id))
                ids.append(ev.id)
            await s.commit()
        await engine.dispose()
        return ids

    return asyncio.run(_run())


async def _count(db_url: str, model: type) -> int:
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            return int((await conn.execute(select(func.count()).select_from(model))).scalar_one())
    finally:
        await engine.dispose()


def _register(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    ).status_code == 201


def test_recommendations_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/recommendations").status_code == 401


def test_recommendations_cold_start_by_quality(settings: Settings) -> None:
    _seed_events(settings.database_url)
    with TestClient(create_app(settings)) as client:
        _register(client, "reco@example.com")
        resp = client.get("/api/v1/recommendations")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 3
        # cold-start (нет user-embedding) → порядок по quality: Event 1 (q=9) первым
        assert items[0]["title"] == "Event 1"


def test_feedback_learns_and_invalidates_cache(settings: Settings) -> None:
    ids = _seed_events(settings.database_url)
    with TestClient(create_app(settings)) as client:
        _register(client, "learn@example.com")
        assert client.get("/api/v1/recommendations").status_code == 200  # прогрев кэша

        # лайк среднего события — учит модель по теме backend
        resp = client.post(
            "/api/v1/interactions", json={"event_id": ids[1], "action": "like"}
        )
        assert resp.status_code == 200

        # interaction + user_topic_stat записаны
        assert asyncio.run(_count(settings.database_url, InteractionModel)) == 1
        assert asyncio.run(_count(settings.database_url, UserTopicStatModel)) == 1

        # кэш инвалидирован → выдача пересчитана (не падает, непустая)
        again = client.get("/api/v1/recommendations")
        assert again.status_code == 200
        assert len(again.json()) == 3
