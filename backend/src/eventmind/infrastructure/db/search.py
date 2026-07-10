"""`SqlAlchemySearchRepository` — строгий SQL-поиск событий по фильтрам.

NULL-сейф по датам только в upcoming-режиме: при явном диапазоне события без
`start_at` отсеиваются (портирует поведение v1 NL-поиска).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.search import SearchQuery
from eventmind.domain.events.entities import Event
from eventmind.infrastructure.db.models import EventModel, EventTopicModel, TopicModel

_GRACE_HOURS = 6


def _to_entity(m: EventModel, topics: list[str]) -> Event:
    return Event(
        id=m.id, source=m.source, title=m.title, description=m.description,
        format=m.format, city=m.city, level=m.level, date=m.date, start_at=m.start_at,
        event_type=m.event_type, target_audience=m.target_audience, source_url=m.source_url,
        summary=m.summary, tech_stack=list(m.tech_stack), seniority=m.seniority,
        quality_score=m.quality_score, hype_score=m.hype_score, series_slug=m.series_slug,
        embedding=list(m.embedding) if m.embedding is not None else None, topics=topics,
        created_at=m.created_at,
    )


class SqlAlchemySearchRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def search(
        self, query: SearchQuery, *, limit: int, now: datetime
    ) -> list[Event]:
        stmt = select(EventModel)

        if query.date_from or query.date_to:
            # явный диапазон: события без start_at отсеиваются
            stmt = stmt.where(EventModel.start_at.isnot(None))
            if query.date_from:
                d = datetime.fromisoformat(query.date_from).replace(tzinfo=UTC)
                stmt = stmt.where(EventModel.start_at >= d)
            if query.date_to:
                d = datetime.fromisoformat(query.date_to).replace(hour=23, minute=59, tzinfo=UTC)
                stmt = stmt.where(EventModel.start_at <= d)
        else:
            cutoff = now - timedelta(hours=_GRACE_HOURS)
            stmt = stmt.where(
                or_(EventModel.start_at.is_(None), EventModel.start_at >= cutoff)
            )

        if query.city:
            stmt = stmt.where(EventModel.city == query.city)
        if query.event_type:
            stmt = stmt.where(EventModel.event_type == query.event_type)
        if query.format:
            stmt = stmt.where(EventModel.format == query.format)
        if query.topics:
            topic_events = (
                select(EventTopicModel.event_id)
                .join(TopicModel, EventTopicModel.topic_id == TopicModel.id)
                .where(TopicModel.code.in_(query.topics))
            )
            stmt = stmt.where(EventModel.id.in_(topic_events))
        if query.free_text:
            pattern = f"%{query.free_text}%"
            stmt = stmt.where(
                or_(EventModel.title.ilike(pattern), EventModel.description.ilike(pattern))
            )

        stmt = stmt.order_by(EventModel.start_at.asc().nullslast()).limit(limit)

        async with self._session_factory() as session:
            events = list((await session.execute(stmt)).scalars().all())
            if not events:
                return []
            topic_map = await self._load_topics(session, [e.id for e in events])
        return [_to_entity(e, topic_map.get(e.id, [])) for e in events]

    async def get_event(self, event_id: int) -> Event | None:
        async with self._session_factory() as session:
            model = await session.get(EventModel, event_id)
            if model is None:
                return None
            topic_map = await self._load_topics(session, [event_id])
        return _to_entity(model, topic_map.get(event_id, []))

    async def _load_topics(
        self, session: AsyncSession, event_ids: list[int]
    ) -> dict[int, list[str]]:
        rows = await session.execute(
            select(EventTopicModel.event_id, TopicModel.code)
            .join(TopicModel, EventTopicModel.topic_id == TopicModel.id)
            .where(EventTopicModel.event_id.in_(event_ids))
        )
        out: dict[int, list[str]] = {}
        for event_id, code in rows.all():
            out.setdefault(event_id, []).append(code)
        return out
