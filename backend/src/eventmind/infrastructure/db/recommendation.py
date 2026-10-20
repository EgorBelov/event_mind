"""`SqlAlchemyRecommendationUnitOfWork` — чтение профиля/статов + online-обучение.

Bayesian-обновление по feedback, ленивый temporal-decay при чтении, текстовый
профиль пользователя (user_profiles) и пересчёт user.embedding по Rocchio:
профиль + понравившиеся события − дизлайкнутые (domain/recommender/user_model).
"""
from __future__ import annotations

from datetime import datetime
from types import TracebackType

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.recommender import BayesianStats, UserPrefs
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.bayesian import (
    PRIOR_ALPHA,
    PRIOR_BETA,
    apply_decay,
    apply_feedback,
    feedback_delta,
)
from eventmind.domain.recommender.user_model import UserProfile, combine_user_embedding
from eventmind.infrastructure.db.models import (
    EventModel,
    EventTopicModel,
    InteractionModel,
    TopicModel,
    UserModel,
    UserProfileModel,
    UserTopicStatModel,
)
from eventmind.infrastructure.recommender.candidate_generator import (
    event_model_to_entity,
    load_event_topics,
)

_POSITIVE_ACTIONS = ("like", "save")
_NEGATIVE_ACTIONS = ("dislike",)


def _profile_to_entity(m: UserProfileModel) -> UserProfile:
    return UserProfile(
        user_id=m.user_id,
        about=m.about,
        role=m.role,
        level=m.level,
        stack=list(m.stack),
        interests=list(m.interests),
        anti_interests=list(m.anti_interests),
        goals=list(m.goals),
        embedding=list(m.embedding) if m.embedding is not None else None,
        updated_at=m.updated_at,
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
            select(
                UserModel.city,
                UserModel.preferred_format,
                UserModel.embedding,
                UserProfileModel.interests,
                UserProfileModel.anti_interests,
            )
            .outerjoin(UserProfileModel, UserProfileModel.user_id == UserModel.id)
            .where(UserModel.id == user_id)
        )
        result = row.first()
        if result is None:
            return None
        city, fmt, emb, interests, anti_interests = result
        return UserPrefs(
            city=city,
            preferred_format=fmt,
            embedding=list(emb) if emb is not None else None,
            interests=list(interests or []),
            anti_interests=list(anti_interests or []),
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
        self,
        user_id: int,
        topic_codes: list[str],
        action: str,
        direction: int,
        *,
        now: datetime,
        gamma: float,
    ) -> None:
        if not topic_codes:
            return
        if feedback_delta(action, direction) == (0.0, 0.0):
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
            # Новая запись — updated_at ещё не выставлен (decay не нужен).
            stat.alpha, stat.beta = apply_feedback(
                stat.alpha, stat.beta, stat.updated_at, action, direction, now=now, gamma=gamma
            )
            stat.updated_at = now

    async def users_with_positive_feedback_on(
        self, event_ids: list[int], *, limit: int
    ) -> list[int]:
        if not event_ids:
            return []
        rows = await self._s.execute(
            select(InteractionModel.user_id)
            .where(
                InteractionModel.action.in_(_POSITIVE_ACTIONS),
                InteractionModel.event_id.in_(event_ids),
            )
            .distinct()
            .order_by(InteractionModel.user_id)
            .limit(limit)
        )
        return [user_id for (user_id,) in rows.all()]

    async def _event_vectors(self, user_id: int, actions: tuple[str, ...]) -> list[list[float]]:
        """Векторы событий с данными действиями; каждое событие — один раз
        (like + save на одном событии не удваивают его вес)."""
        interacted = select(InteractionModel.event_id).where(
            InteractionModel.user_id == user_id, InteractionModel.action.in_(actions)
        )
        rows = await self._s.execute(
            select(EventModel.embedding).where(
                EventModel.id.in_(interacted), EventModel.embedding.isnot(None)
            )
        )
        return [list(v) for (v,) in rows.all() if v is not None]

    async def recompute_user_embedding(self, user_id: int) -> None:
        """user.embedding = Rocchio(профиль, like/save, dislike); None — нет сигнала."""
        user = await self._s.get(UserModel, user_id)
        if user is None:
            return
        profile_row = await self._s.get(UserProfileModel, user_id)
        profile_vec = (
            list(profile_row.embedding)
            if profile_row is not None and profile_row.embedding is not None
            else None
        )
        user.embedding = combine_user_embedding(
            profile_vec,
            await self._event_vectors(user_id, _POSITIVE_ACTIONS),
            await self._event_vectors(user_id, _NEGATIVE_ACTIONS),
        )

    async def get_profile(self, user_id: int) -> UserProfile | None:
        model = await self._s.get(UserProfileModel, user_id)
        return _profile_to_entity(model) if model is not None else None

    async def save_profile(self, profile: UserProfile) -> None:
        model = await self._s.get(UserProfileModel, profile.user_id)
        if model is None:
            model = UserProfileModel(user_id=profile.user_id)
            self._s.add(model)
        model.about = profile.about
        model.role = profile.role
        model.level = profile.level
        model.stack = list(profile.stack)
        model.interests = list(profile.interests)
        model.anti_interests = list(profile.anti_interests)
        model.goals = list(profile.goals)
        model.embedding = profile.embedding
        if profile.updated_at is not None:
            model.updated_at = profile.updated_at
        # recompute_user_embedding в той же транзакции читает профиль через get
        await self._s.flush()

    async def list_saved(
        self, user_id: int, *, offset: int, limit: int
    ) -> tuple[list[Event], int]:
        saved = (
            select(
                InteractionModel.event_id,
                func.max(InteractionModel.created_at).label("saved_at"),
            )
            .where(InteractionModel.user_id == user_id, InteractionModel.action == "save")
            .group_by(InteractionModel.event_id)
            .subquery()
        )
        total = int(
            (await self._s.execute(select(func.count()).select_from(saved))).scalar_one()
        )
        rows = await self._s.execute(
            select(EventModel)
            .join(saved, saved.c.event_id == EventModel.id)
            .order_by(saved.c.saved_at.desc(), EventModel.id)
            .offset(offset)
            .limit(limit)
        )
        models = list(rows.scalars().all())
        topics = await load_event_topics(self._s, [m.id for m in models])
        return [event_model_to_entity(m, topics.get(m.id, [])) for m in models], total

    async def remove_interactions(self, user_id: int, event_id: int, action: str) -> int:
        where = (
            InteractionModel.user_id == user_id,
            InteractionModel.event_id == event_id,
            InteractionModel.action == action,
        )
        count = int(
            (
                await self._s.execute(
                    select(func.count()).select_from(InteractionModel).where(*where)
                )
            ).scalar_one()
        )
        if count:
            await self._s.execute(delete(InteractionModel).where(*where))
        return count

    async def known_topic_codes(self, *, limit: int) -> list[str]:
        rows = await self._s.execute(
            select(TopicModel.code)
            .join(EventTopicModel, EventTopicModel.topic_id == TopicModel.id)
            .group_by(TopicModel.code)
            .order_by(func.count().desc(), TopicModel.code)
            .limit(limit)
        )
        return [code for (code,) in rows.all()]
