"""Use-case'ы ingestion: загрузка источников и LLM-нормализация в events.

Пайплайн: source → raw_events → нормализация (LLM) → events. Идемпотентность
(по source+url), ретраи с DLQ (status=failed при исчерпании), изоляция сбоев
(падение одного сырья/источника не рушит остальные).
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

from eventmind.application.ingestion.config import IngestionConfig
from eventmind.application.ingestion.normalizer import EventNormalizer
from eventmind.application.ports.embedding import EmbeddingProvider
from eventmind.application.ports.events import EventsUnitOfWork, EventsUnitOfWorkFactory
from eventmind.application.ports.queue import TaskQueue
from eventmind.application.ports.sources import EventSource
from eventmind.domain.events.entities import Event, RawEvent
from eventmind.domain.events.series import compute_series_slug
from eventmind.domain.events.value_objects import RawEventStatus

_logger = structlog.get_logger("eventmind.ingestion")

NORMALIZE_TASK = "normalize_raw_events"


@dataclass(slots=True)
class LoadResult:
    source: str
    fetched: int
    added: int
    duplicates: int


@dataclass(slots=True)
class NormalizeResult:
    processed: int = 0
    events_created: int = 0
    non_it: int = 0
    failed: int = 0


class LoadSource:
    """Скачать сырьё одного источника в raw_events (идемпотентно) + запустить нормализацию."""

    def __init__(
        self,
        uow_factory: EventsUnitOfWorkFactory,
        task_queue: TaskQueue,
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = task_queue

    async def execute(self, source: EventSource, *, limit: int = 20) -> LoadResult:
        drafts = await source.fetch(limit)
        added = 0
        async with self._uow_factory() as uow:
            for draft in drafts:
                raw = RawEvent(
                    source=source.name,
                    title=draft.title,
                    raw_description=draft.raw_description,
                    source_url=draft.source_url,
                )
                if await uow.raw_events.add_if_absent(raw) is not None:
                    added += 1
            await uow.commit()
        if added:
            await self._queue.enqueue(NORMALIZE_TASK)
        return LoadResult(
            source=source.name, fetched=len(drafts), added=added, duplicates=len(drafts) - added
        )


class LoadAllSources:
    """Пройти по всем источникам реестра с изоляцией сбоев."""

    def __init__(self, sources: dict[str, EventSource], load_source: LoadSource) -> None:
        self._sources = sources
        self._load_source = load_source

    async def execute(self, *, limit: int = 20) -> list[LoadResult]:
        results: list[LoadResult] = []
        for name, source in self._sources.items():
            try:
                results.append(await self._load_source.execute(source, limit=limit))
            except Exception as exc:  # источник не должен рушить остальные
                _logger.warning("ingest_source_failed", source=name, error=str(exc))
                results.append(LoadResult(source=name, fetched=0, added=0, duplicates=0))
        return results


class NormalizeRawEvents:
    """Нормализовать пачку сырых событий в events (LLM + эмбеддинг)."""

    def __init__(
        self,
        uow_factory: EventsUnitOfWorkFactory,
        normalizer: EventNormalizer,
        embedding: EmbeddingProvider,
        config: IngestionConfig,
    ) -> None:
        self._uow_factory = uow_factory
        self._normalizer = normalizer
        self._embedding = embedding
        self._config = config

    async def execute(
        self,
        *,
        limit: int | None = None,
        statuses: list[RawEventStatus] | None = None,
    ) -> NormalizeResult:
        limit = limit or self._config.normalize_batch_size
        statuses = statuses or [RawEventStatus.RAW, RawEventStatus.FAILED]
        result = NormalizeResult()

        async with self._uow_factory() as uow:
            raws = await uow.raw_events.fetch_for_processing(
                statuses, limit=limit, max_retries=self._config.max_normalize_retries
            )
            for raw in raws:
                result.processed += 1
                await self._process_one(uow, raw, result)
            await uow.commit()
        return result

    async def _process_one(
        self, uow: EventsUnitOfWork, raw: RawEvent, result: NormalizeResult
    ) -> None:
        try:
            normalized = await self._normalizer.normalize(
                title=raw.title,
                raw_description=raw.raw_description,
                source_url=raw.source_url,
            )
        except Exception as exc:
            raw.mark_failed(str(exc), max_retries=self._config.max_normalize_retries)
            await uow.raw_events.update(raw)
            result.failed += 1
            return

        if not normalized.is_event:
            raw.mark_non_it()
            await uow.raw_events.update(raw)
            result.non_it += 1
            return

        # Идемпотентность: событие с таким source_url уже есть → просто закрываем сырьё.
        if raw.source_url and await uow.events.exists_by_source_url(raw.source_url):
            raw.mark_normalized()
            await uow.raw_events.update(raw)
            return

        topic_ids = await uow.topics.ensure_codes(normalized.topics)
        embedding = await self._safe_embed(normalized.title, normalized.description)

        event = Event(
            source=raw.source,
            title=normalized.title or raw.title,
            description=normalized.description or raw.raw_description,
            format=normalized.format,
            city=normalized.city,
            level=normalized.level,
            date=normalized.date,
            start_at=normalized.start_at,
            event_type=normalized.event_type,
            target_audience=normalized.target_audience or None,
            source_url=raw.source_url,
            tech_stack=normalized.tech_stack,
            seniority=normalized.seniority,
            quality_score=normalized.quality_score,
            hype_score=normalized.hype_score,
            series_slug=compute_series_slug(normalized.title or raw.title, normalized.city),
            topics=normalized.topics,
            embedding=embedding,
        )
        await uow.events.add(event, list(topic_ids.values()))
        raw.mark_normalized()
        await uow.raw_events.update(raw)
        result.events_created += 1

    async def _safe_embed(self, title: str, description: str) -> list[float] | None:
        """Эмбеддинг события; сбой провайдера не рушит нормализацию (backfill в M4)."""
        try:
            return await self._embedding.embed_text(f"{title}\n{description}".strip())
        except Exception as exc:
            _logger.warning("event_embedding_failed", error=str(exc))
            return None


class GetIngestionStatus:
    def __init__(self, uow_factory: EventsUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self) -> dict[str, object]:
        async with self._uow_factory() as uow:
            raw_counts = await uow.raw_events.count_by_status()
            events_total = await uow.events.count()
        return {"raw_events": raw_counts, "events_total": events_total}
