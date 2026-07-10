"""Use-case'ы рекомендера: read-only выдача (с кэшем) и online-обучение по feedback."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from eventmind.application.ports.cache import Cache
from eventmind.application.ports.recommender import (
    BayesianStats,
    CandidateGenerator,
    RecommendationUnitOfWorkFactory,
    UserPrefs,
)
from eventmind.application.ports.security import Clock
from eventmind.application.recommender.config import RecommenderConfig
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.scoring import EventFeatures, UserContext
from eventmind.domain.recommender.weights import ScoringWeights

# Разрешённые действия feedback (like/save — позитив, dislike — негатив, view — лог).
VALID_ACTIONS = frozenset({"like", "dislike", "save", "view"})


def _cache_key(user_id: int) -> str:
    return f"reco:{user_id}"


@dataclass(slots=True)
class RecommendationItem:
    event_id: int
    title: str
    description: str
    date: str
    city: str
    format: str
    event_type: str | None
    source_url: str | None
    score: float
    topics: list[str] = field(default_factory=list)


def _user_context(prefs: UserPrefs, stats: BayesianStats) -> UserContext:
    """Собрать профиль скоринга: интересы — темы с положительным перевесом (α>β)."""
    topics = {code for code, (a, b) in stats.items() if a > b}
    weights = {code: int(round(a - b)) for code, (a, b) in stats.items() if a > b}
    return UserContext(
        topics=topics,
        topic_weights=weights,
        preferred_format=prefs.preferred_format,
        city=prefs.city,
        embedding=prefs.embedding,
    )


def _features(event: Event) -> EventFeatures:
    assert event.id is not None
    return EventFeatures(
        id=event.id,
        topics=event.topics,
        format=event.format,
        city=event.city,
        quality_score=event.quality_score,
        hype_score=event.hype_score,
        start_at=event.start_at,
        embedding=event.embedding,
        series_slug=event.series_slug,
    )


def _to_item(event: Event, score: float) -> RecommendationItem:
    assert event.id is not None
    return RecommendationItem(
        event_id=event.id,
        title=event.title,
        description=event.description,
        date=event.date,
        city=event.city,
        format=event.format,
        event_type=event.event_type,
        source_url=event.source_url,
        score=round(score, 4),
        topics=event.topics,
    )


class GetRecommendations:
    """Read-only выдача рекомендаций (hot-path через кэш)."""

    def __init__(
        self,
        uow_factory: RecommendationUnitOfWorkFactory,
        candidate_generator: CandidateGenerator,
        ranker: HybridRanker,
        cache: Cache,
        clock: Clock,
        config: RecommenderConfig,
        weights: ScoringWeights,
    ) -> None:
        self._uow_factory = uow_factory
        self._candidates = candidate_generator
        self._ranker = ranker
        self._cache = cache
        self._clock = clock
        self._config = config
        self._weights = weights

    async def execute(self, user_id: int) -> list[RecommendationItem]:
        cached = await self._cache.get(_cache_key(user_id))
        if cached is not None:
            return [RecommendationItem(**row) for row in json.loads(cached)]

        now = self._clock.now()
        async with self._uow_factory() as uow:
            prefs = await uow.get_user_prefs(user_id) or UserPrefs()
            stats = await uow.load_bayesian_stats(
                user_id, now=now, gamma=self._weights.bayes_decay_per_day
            )

        candidates = await self._candidates.generate(
            user_embedding=prefs.embedding,
            city=prefs.city,
            limit=self._config.candidate_limit,
            now=now,
        )
        by_id = {ev.id: ev for ev in candidates if ev.id is not None}
        ranked = self._ranker.rank(
            _user_context(prefs, stats),
            [_features(ev) for ev in candidates if ev.id is not None],
            stats,
            now=now,
            limit=self._config.result_limit,
        )
        items = [_to_item(by_id[s.event_id], s.score) for s in ranked if s.event_id in by_id]

        await self._cache.set(
            _cache_key(user_id),
            json.dumps([asdict(it) for it in items], ensure_ascii=False),
            ttl_seconds=self._config.cache_ttl_seconds,
        )
        return items


class RecordInteraction:
    """Записать feedback + онлайн-обновить Bayesian-статы + прогреть эмбеддинг + сброс кэша."""

    def __init__(
        self, uow_factory: RecommendationUnitOfWorkFactory, cache: Cache
    ) -> None:
        self._uow_factory = uow_factory
        self._cache = cache

    async def execute(self, user_id: int, event_id: int, action: str) -> None:
        if action not in VALID_ACTIONS:
            raise ValueError(f"Недопустимое действие: {action!r}")
        async with self._uow_factory() as uow:
            await uow.record_interaction(user_id, event_id, action)
            if action in ("like", "dislike", "save"):
                codes = await uow.get_event_topic_codes(event_id)
                await uow.apply_feedback_to_stats(user_id, codes, action, 1)
                await uow.recompute_user_embedding(user_id)
            await uow.commit()
        await self._cache.delete(_cache_key(user_id))
