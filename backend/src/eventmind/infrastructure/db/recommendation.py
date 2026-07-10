"""`SqlAlchemyRecommendationUnitOfWork` — чтение профиля/статов + online-обучение.

Bayesian-обновление по feedback, ленивый temporal-decay при чтении, прогрев
user.embedding как среднее эмбеддингов понравившихся событий.
"""
from __future__ import annotations

from datetime import datetime
from types import TracebackType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.recommender import BayesianStats, UserPrefs
from eventmind.domain.recommender.bayesian import (
    PRIOR_ALPHA,
    PRIOR_BETA,
    apply_decay,
    feedback_delta,
)
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    InteractionModel,
    TopicModel,
    UserModel,
    UserTopicStatModel,
)


class SqlAlchemyRecommendationUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyRecommendationUnitOfWork:
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    @property
    def _s(self) -> AsyncSession:
        assert self._session is not None
        return self._session

    async def commit(self) -> None:
        await self._s.commit()

    async def get_user_prefs(self, user_id: int) -> UserPrefs | None:
        row = await self._s.execute(
            select(UserModel.city, UserModel.preferred_format, UserModel.embedding).where(
                UserModel.id == user_id
            )
        )
        result = row.first()
        if result is None:
            return None
        city, fmt, emb = result
        return UserPrefs(
            city=city,
            preferred_format=fmt,
            embedding=list(emb) if emb is not None else None,
        )

    async def load_bayesian_stats(
        self, user_id: int, *, now: datetime, gamma: float
    ) -> BayesianStats:
        rows = await self._s.execute(
            select(TopicModel.code, UserTopicStatModel.alpha, UserTopicStatModel.beta,
                   UserTopicStatModel.updated_at)
            .join(TopicModel, UserTopicStatModel.topic_id == TopicModel.id)
            .where(UserTopicStatModel.user_id == user_id)
        )
        out: BayesianStats = {}
        for code, alpha, beta, updated_at in rows.all():
            out[code] = apply_decay(alpha, beta, updated_at, now=now, gamma=gamma)
        return out

    async def get_event_topic_codes(self, event_id: int) -> list[str]:
        rows = await self._s.execute(
            select(TopicModel.code)
            .join(EventTopicModel, EventTopicModel.topic_id == TopicModel.id)
            .where(EventTopicModel.event_id == event_id)
        )
        return [code for (code,) in rows.all()]

    async def record_interaction(self, user_id: int, event_id: int, action: str) -> None:
        self._s.add(InteractionModel(user_id=user_id, event_id=event_id, action=action))

    async def apply_feedback_to_stats(
        self, user_id: int, topic_codes: list[str], action: str, direction: int
    ) -> None:
        if not topic_codes:
            return
        d_alpha, d_beta = feedback_delta(action, direction)
        if d_alpha == 0.0 and d_beta == 0.0:
            return
        topic_rows = await self._s.execute(
            select(TopicModel.id, TopicModel.code).where(TopicModel.code.in_(topic_codes))
        )
        for topic_id, _code in topic_rows.all():
            stat = (
                await self._s.execute(
                    select(UserTopicStatModel).where(
                        UserTopicStatModel.user_id == user_id,
                        UserTopicStatModel.topic_id == topic_id,
                    )
                )
            ).scalar_one_or_none()
            if stat is None:
                stat = UserTopicStatModel(
                    user_id=user_id, topic_id=topic_id, alpha=PRIOR_ALPHA, beta=PRIOR_BETA
                )
                self._s.add(stat)
            stat.alpha = max(PRIOR_ALPHA, stat.alpha + d_alpha)
            stat.beta = max(PRIOR_BETA, stat.beta + d_beta)

    async def recompute_user_embedding(self, user_id: int) -> None:
        """user.embedding = среднее эмбеддингов понравившихся/сохранённых событий."""
        rows = await self._s.execute(
            select(EventModel.embedding)
            .join(InteractionModel, InteractionModel.event_id == EventModel.id)
            .where(
                InteractionModel.user_id == user_id,
                InteractionModel.action.in_(("like", "save")),
                EventModel.embedding.isnot(None),
            )
        )
        vectors = [list(v) for (v,) in rows.all() if v is not None]
        if not vectors:
            return
        dim = len(vectors[0])
        mean = [sum(vec[i] for vec in vectors) / len(vectors) for i in range(dim)]
        user = await self._s.get(UserModel, user_id)
        if user is not None:
            user.embedding = mean
