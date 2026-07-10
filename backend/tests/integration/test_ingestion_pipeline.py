"""Integration: пайплайн ingestion (load идемпотентно → normalize) на живой БД.

Источник и LLM-нормализатор фейковые (детерминизм), БД реальная (pgvector).
"""
from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from eventmind.application.ingestion.config import IngestionConfig
from eventmind.application.ingestion.normalizer import NormalizedResult
from eventmind.application.ingestion.use_cases import LoadSource, NormalizeRawEvents
from eventmind.application.ports.sources import RawEventDraft
from eventmind.infrastructure.db.events_uow import SqlAlchemyEventsUnitOfWork
from eventmind.infrastructure.db.models import EventModel, EventTopicModel

pytestmark = pytest.mark.usefixtures("clean_tables")

CONFIG = IngestionConfig(normalize_batch_size=50, max_normalize_retries=3)


class FakeSource:
    name = "fake"

    def __init__(self, drafts: list[RawEventDraft]) -> None:
        self._drafts = drafts

    async def fetch(self, limit: int = 20) -> list[RawEventDraft]:
        return self._drafts[:limit]


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, task: str, **kw: object) -> None:
        self.enqueued.append(task)


class FakeNormalizer:
    """news→не событие; boom→исключение; иначе IT-событие с topics=[backend]."""

    async def normalize(
        self, *, title: str, raw_description: str, source_url: str | None
    ) -> NormalizedResult:
        if "boom" in title.lower():
            raise RuntimeError("llm down")
        if "news" in title.lower():
            return NormalizedResult(
                is_event=False, title=title, description="", format="unknown",
                city="unknown", level="unknown", date="", topics=[],
                event_type="unknown", target_audience="", tech_stack=[],
                seniority="any", quality_score=None, hype_score=None,
            )
        return NormalizedResult(
            is_event=True, title=title, description=raw_description, format="offline",
            city="moscow", level="middle", date="", topics=["backend"],
            event_type="meetup", target_audience="", tech_stack=["Python"],
            seniority="middle", quality_score=8, hype_score=7,
        )


class FakeEmbedding:
    dimension = 384
    model_version = "fake"

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

    async def embed_text(self, text: str) -> list[float]:
        return [0.1] * 384


def _factory(session_factory: async_sessionmaker):
    return lambda: SqlAlchemyEventsUnitOfWork(session_factory)


async def _count(session_factory: async_sessionmaker, model: type) -> int:
    async with session_factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def test_load_is_idempotent_and_normalize_creates_events(
    session_factory: async_sessionmaker,
) -> None:
    drafts = [
        RawEventDraft(title="Python MeetUp #14", raw_description="doc", source_url="http://e/1"),
        RawEventDraft(title="Company News", raw_description="pr", source_url="http://e/2"),
        RawEventDraft(title="dup", raw_description="x", source_url="http://e/1"),  # дубль url
    ]
    queue = FakeQueue()
    load = LoadSource(_factory(session_factory), queue)

    r1 = await load.execute(FakeSource(drafts), limit=20)
    assert r1.fetched == 3 and r1.added == 2 and r1.duplicates == 1
    assert queue.enqueued == ["normalize_raw_events"]

    # повторная загрузка — ничего нового (идемпотентность по source+url)
    r2 = await load.execute(FakeSource(drafts), limit=20)
    assert r2.added == 0

    normalize = NormalizeRawEvents(
        _factory(session_factory), FakeNormalizer(), FakeEmbedding(), CONFIG  # type: ignore[arg-type]
    )
    result = await normalize.execute()
    assert result.processed == 2  # два уникальных raw
    assert result.events_created == 1  # meetup
    assert result.non_it == 1          # news

    assert await _count(session_factory, EventModel) == 1
    assert await _count(session_factory, EventTopicModel) == 1  # topic слинкован

    async with session_factory() as s:
        event = (await s.execute(select(EventModel))).scalars().one()
    assert event.city == "moscow"
    # снят #14 (номер выпуска); город добавляется суффиксом (анти-флуд по городам)
    assert event.series_slug == "python-meetup--moscow"
    assert event.embedding is not None
    assert event.tech_stack == ["Python"]


async def test_failed_normalization_goes_to_dlq_with_retry_count(
    session_factory: async_sessionmaker,
) -> None:
    drafts = [RawEventDraft(title="boom event", raw_description="x", source_url="http://e/9")]
    await LoadSource(_factory(session_factory), FakeQueue()).execute(FakeSource(drafts))

    normalize = NormalizeRawEvents(
        _factory(session_factory), FakeNormalizer(), FakeEmbedding(), CONFIG  # type: ignore[arg-type]
    )
    r1 = await normalize.execute()
    assert r1.failed == 1

    # статус failed, retry_count вырос
    from eventmind.infrastructure.db.models import RawEventModel

    async with session_factory() as s:
        raw = (await s.execute(select(RawEventModel))).scalars().one()
    assert raw.status == "failed"
    assert raw.retry_count == 1

    # повторные прогоны увеличивают retry_count, пока не исчерпан лимит → больше не берём
    await normalize.execute()  # retry 2
    await normalize.execute()  # retry 3 == max → в следующий раз не выбирается
    r_after = await normalize.execute()
    assert r_after.processed == 0  # исчерпал ретраи, из очереди обработки выпал
