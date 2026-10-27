"""Integration: три ретривера гибридного поиска на настоящем Postgres (P1 №7).

Проверяем то, что не проверить фейками: русскую морфологию `to_tsvector`
(«митапы» находит «митап»), OR-запрос с ранжированием, порог cosine у kNN и
общие жёсткие фильтры.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eventmind.application.ports.search import SearchQuery
from eventmind.config import Settings
from eventmind.infrastructure.db.models import EventModel
from eventmind.infrastructure.db.search import SqlAlchemySearchRepository

pytestmark = pytest.mark.usefixtures("clean_tables")

NOW = datetime.now(UTC)
GO = [1.0] + [0.0] * 383
FRONT = [0.0, 1.0] + [0.0] * 382


def _seed(db_url: str) -> dict[str, int]:
    async def run() -> dict[str, int]:
        engine = create_async_engine(db_url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, int] = {}
        async with sf() as s:
            for key, title, desc, city, vec in (
                ("kafka", "Митап по Kafka", "Стриминг и очереди сообщений", "moscow", GO),
                ("go", "Go-конференция", "Конкурентность в Go, highload", "moscow", GO),
                ("react", "React Day", "Фронтенд и хуки", "spb", FRONT),
            ):
                ev = EventModel(
                    source="seed", title=title, description=desc, format="offline", city=city,
                    level="any", date="", start_at=NOW + timedelta(days=3), tech_stack=[],
                    embedding=vec,
                )
                s.add(ev)
                await s.flush()
                ids[key] = ev.id
            await s.commit()
        await engine.dispose()
        return ids

    return asyncio.run(run())


def test_text_search_uses_russian_morphology_and_or_terms(settings: Settings) -> None:
    ids = _seed(settings.database_url)
    engine = create_async_engine(settings.database_url)
    repo = SqlAlchemySearchRepository(async_sessionmaker(engine, expire_on_commit=False))

    async def run() -> None:
        found = await repo.text_search(SearchQuery(), "митапы про kafka", limit=5, now=NOW)
        assert [e.id for e in found] == [ids["kafka"]]
        # OR лексем: «конференции» или «хуки» — оба события, город фильтрует жёстко
        both = await repo.text_search(SearchQuery(), "конференции хуки", limit=5, now=NOW)
        assert {e.id for e in both} == {ids["go"], ids["react"]}
        moscow = await repo.text_search(
            SearchQuery(city="moscow"), "конференции хуки", limit=5, now=NOW
        )
        assert [e.id for e in moscow] == [ids["go"]]
        assert await repo.text_search(SearchQuery(), "!!!", limit=5, now=NOW) == []
        await engine.dispose()

    asyncio.run(run())


def test_semantic_search_respects_threshold_and_filters(settings: Settings) -> None:
    ids = _seed(settings.database_url)
    engine = create_async_engine(settings.database_url)
    repo = SqlAlchemySearchRepository(async_sessionmaker(engine, expire_on_commit=False))

    async def run() -> None:
        near = await repo.semantic_search(
            SearchQuery(), GO, limit=5, now=NOW, min_similarity=0.5
        )
        assert {e.id for e in near} == {ids["kafka"], ids["go"]}  # React ортогонален
        spb = await repo.semantic_search(
            SearchQuery(city="spb"), FRONT, limit=5, now=NOW, min_similarity=0.5
        )
        assert [e.id for e in spb] == [ids["react"]]
        await engine.dispose()

    asyncio.run(run())
