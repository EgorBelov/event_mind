"""async-SQLAlchemy-репозитории событий (raw_events / events / topics).

Идемпотентность: raw по (source, source_url), event по source_url. Топики
создаются лениво (`ensure_codes`) и линкуются в event_topics.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eventmind.domain.events.entities import Event, RawEvent
from eventmind.domain.events.taxonomy import topic_title
from eventmind.domain.events.value_objects import RawEventStatus
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    RawEventModel,
    TopicModel,
)


def _raw_to_entity(m: RawEventModel) -> RawEvent:
    return RawEvent(
        id=m.id,
        source=m.source,
        title=m.title,
        raw_description=m.raw_description,
        source_url=m.source_url,
        status=RawEventStatus(m.status),
        error=m.error,
        retry_count=m.retry_count,
        created_at=m.created_at,
    )


class SqlAlchemyRawEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_if_absent(self, raw: RawEvent) -> RawEvent | None:
        if raw.source_url is not None:
            existing = await self._session.execute(
                select(RawEventModel.id).where(
                    RawEventModel.source == raw.source,
                    RawEventModel.source_url == raw.source_url,
                )
            )
            if existing.scalar_one_or_none() is not None:
                return None
        model = RawEventModel(
            source=raw.source,
            title=raw.title,
            raw_description=raw.raw_description,
            source_url=raw.source_url,
            status=raw.status.value,
            retry_count=raw.retry_count,
        )
        self._session.add(model)
        await self._session.flush()
        raw.id = model.id
        raw.created_at = model.created_at
        return raw

    async def get_by_id(self, raw_id: int) -> RawEvent | None:
        model = await self._session.get(RawEventModel, raw_id)
        return _raw_to_entity(model) if model else None

    async def fetch_for_processing(
        self, statuses: list[RawEventStatus], *, limit: int, max_retries: int
    ) -> list[RawEvent]:
        result = await self._session.execute(
            select(RawEventModel)
            .where(
                RawEventModel.status.in_([s.value for s in statuses]),
                RawEventModel.retry_count < max_retries,
            )
            .order_by(RawEventModel.id)
            .limit(limit)
        )
        return [_raw_to_entity(m) for m in result.scalars().all()]

    async def update(self, raw: RawEvent) -> None:
        assert raw.id is not None
        model = await self._session.get(RawEventModel, raw.id)
        if model is None:
            return
        model.status = raw.status.value
        model.error = raw.error
        model.retry_count = raw.retry_count

    async def count_by_status(self) -> dict[str, int]:
        result = await self._session.execute(
            select(RawEventModel.status, func.count()).group_by(RawEventModel.status)
        )
        return {status: int(count) for status, count in result.all()}


class SqlAlchemyEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_by_source_url(self, source_url: str) -> bool:
        result = await self._session.execute(
            select(EventModel.id).where(EventModel.source_url == source_url).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def add(self, event: Event, topic_ids: list[int]) -> Event:
        model = EventModel(
            source=event.source,
            title=event.title,
            description=event.description,
            format=event.format,
            city=event.city,
            level=event.level,
            date=event.date,
            start_at=event.start_at,
            event_type=event.event_type,
            target_audience=event.target_audience,
            source_url=event.source_url,
            summary=event.summary,
            tech_stack=event.tech_stack,
            seniority=event.seniority,
            quality_score=event.quality_score,
            hype_score=event.hype_score,
            series_slug=event.series_slug,
            embedding=event.embedding,
        )
        self._session.add(model)
        await self._session.flush()
        event.id = model.id
        event.created_at = model.created_at
        for topic_id in topic_ids:
            self._session.add(EventTopicModel(event_id=model.id, topic_id=topic_id))
        return event

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(EventModel))
        return int(result.scalar_one())


class SqlAlchemyTopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_codes(self, codes: list[str]) -> dict[str, int]:
        if not codes:
            return {}
        unique = list(dict.fromkeys(codes))
        existing = await self._session.execute(
            select(TopicModel).where(TopicModel.code.in_(unique))
        )
        mapping: dict[str, int] = {m.code: m.id for m in existing.scalars().all()}
        for code in unique:
            if code in mapping:
                continue
            model = TopicModel(code=code, title=topic_title(code))
            self._session.add(model)
            await self._session.flush()
            mapping[code] = model.id
        return mapping
