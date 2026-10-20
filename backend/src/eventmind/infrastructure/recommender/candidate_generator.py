"""`PgvectorCandidateGenerator` — первая стадия: kNN по user-embedding + upcoming.

Масштабируется на рост каталога: kNN на HNSW-индексе ограничивает скоринг
top-N кандидатами, а не всей таблицей. Cold-start (нет user-embedding) —
свежие качественные события.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.domain.events.entities import Event
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    InteractionModel,
    TopicModel,
)

_GRACE_HOURS = 6  # показываем события, начавшиеся до 6 ч назад (весь день конференции)
# Уже оценённое не показываем снова (view — только лог, не исключает).
_EXCLUDING_ACTIONS = ("like", "dislike", "save")


def event_model_to_entity(m: EventModel, topics: list[str]) -> Event:
    return Event(
        id=m.id,
        source=m.source,
        title=m.title,
        description=m.description,
        format=m.format,
        city=m.city,
        level=m.level,
        date=m.date,
        start_at=m.start_at,
        event_type=m.event_type,
        target_audience=m.target_audience,
        source_url=m.source_url,
        summary=m.summary,
        tech_stack=list(m.tech_stack),
        seniority=m.seniority,
        quality_score=m.quality_score,
        hype_score=m.hype_score,
        series_slug=m.series_slug,
        embedding=list(m.embedding) if m.embedding is not None else None,
        topics=topics,
        created_at=m.created_at,
    )


class PgvectorCandidateGenerator:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def generate(
        self,
        *,
        user_embedding: list[float] | None,
        city: str | None,
        limit: int,
        now: datetime,
        exclude_interacted_by: int | None = None,
    ) -> list[Event]:
        cutoff = now - timedelta(hours=_GRACE_HOURS)
        # upcoming-only, NULL-сейф: события без даты остаются в выборке.
        filters = [or_(EventModel.start_at.is_(None), EventModel.start_at >= cutoff)]
        if exclude_interacted_by is not None:
            filters.append(
                EventModel.id.not_in(
                    select(InteractionModel.event_id).where(
                        InteractionModel.user_id == exclude_interacted_by,
                        InteractionModel.action.in_(_EXCLUDING_ACTIONS),
                    )
                )
            )

        if user_embedding is not None:
            query = (
                select(EventModel)
                .where(*filters, EventModel.embedding.isnot(None))
                .order_by(EventModel.embedding.cosine_distance(user_embedding))
                .limit(limit)
            )
        else:
            # cold-start: свежие качественные события.
            query = (
                select(EventModel)
                .where(*filters)
                .order_by(
                    EventModel.quality_score.desc().nullslast(),
                    EventModel.start_at.asc().nullslast(),
                )
                .limit(limit)
            )

        async with self._session_factory() as session:
            events = list((await session.execute(query)).scalars().all())
            if not events:
                return []
            topic_map = await load_event_topics(session, [e.id for e in events])
        return [event_model_to_entity(e, topic_map.get(e.id, [])) for e in events]


async def load_event_topics(session: AsyncSession, event_ids: list[int]) -> dict[int, list[str]]:
    """{event_id: [topic codes]} одним запросом."""
    if not event_ids:
        return {}
    rows = await session.execute(
        select(EventTopicModel.event_id, TopicModel.code)
        .join(TopicModel, EventTopicModel.topic_id == TopicModel.id)
        .where(EventTopicModel.event_id.in_(event_ids))
    )
    out: dict[int, list[str]] = {}
    for event_id, code in rows.all():
        out.setdefault(event_id, []).append(code)
    return out
