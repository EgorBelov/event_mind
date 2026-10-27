"""«Мир» симуляции в памяти: корпус событий + один пользователь.

Реализует порты, нужные агенту, без БД и Redis — чтобы в эксперименте работали
настоящие use-case'ы и инструменты приложения (NlSearch, GetRecommendations,
RecordInteraction, ApplyProfileChanges, ExplainEvent):
- `SearchRepository` — строгий поиск по фильтрам (как SQL в приложении);
- `CandidateGenerator` — kNN по cosine (как pgvector) / cold-start по quality;
- `RecommendationUnitOfWork` — профиль, оценки, Bayesian-статы, Rocchio;
- смена города/формата — аналог accounts `UpdateProfile`.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from eval.real.data import CorpusEvent
from eval.real.systems import parse_start
from eventmind.application.agent.config import AgentConfig
from eventmind.application.agent.session import AgentSessionStore
from eventmind.application.agent.tools import (
    AgentToolbox,
    ExplainEventTool,
    GetEventTool,
    GetProfileTool,
    RecommendTool,
    RecordFeedbackTool,
    SearchEventsTool,
    UpdateProfileTool,
    UpdateSettingsTool,
)
from eventmind.application.agent.use_cases import AgentTurn
from eventmind.application.ports.agent import AgentTurnRecord
from eventmind.application.ports.llm import LLMGateway, ToolCallingLLM
from eventmind.application.ports.recommender import BayesianStats, UserPrefs
from eventmind.application.ports.search import SearchQuery
from eventmind.application.recommender.config import RecommenderConfig
from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.recommender.profile import (
    ApplyProfileChanges,
    GetUserProfile,
    UpdateUserProfile,
)
from eventmind.application.recommender.profile_extractor import ProfileExtractor
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    RecordInteraction,
)
from eventmind.application.search.use_cases import NlSearch
from eventmind.domain.events.entities import Event
from eventmind.domain.events.taxonomy import canonicalize_city
from eventmind.domain.recommender.bayesian import PRIOR_ALPHA, PRIOR_BETA, feedback_delta
from eventmind.domain.recommender.scoring import cosine_similarity
from eventmind.domain.recommender.user_model import UserProfile, combine_user_embedding
from eventmind.domain.recommender.weights import ScoringWeights

USER_ID = 1
_GRACE_HOURS = 6
_EXCLUDING = ("like", "dislike", "save")
_POSITIVE = ("like", "save")

EncodeQuery = Callable[[str], Awaitable[list[float]]]


def _day(iso: str, *, end: bool = False) -> datetime:
    day = datetime.fromisoformat(iso).replace(tzinfo=UTC)
    return day.replace(hour=23, minute=59) if end else day


def corpus_event_to_entity(ev: CorpusEvent, embedding: list[float] | None) -> Event:
    return Event(
        id=ev.id,
        source=ev.source,
        title=ev.title,
        description=ev.description,
        format=ev.format,
        city=ev.city,
        level=ev.seniority or "any",
        date=ev.start_at or "",
        start_at=parse_start(ev.start_at),
        event_type=ev.event_type,
        source_url=ev.source_url,
        tech_stack=list(ev.tech_stack),
        seniority=ev.seniority,
        quality_score=ev.quality_score,
        hype_score=ev.hype_score,
        series_slug=ev.series_slug,
        topics=list(ev.topics),
        embedding=embedding,
    )


@dataclass
class UserState:
    profile: UserProfile = field(default_factory=lambda: UserProfile(user_id=USER_ID))
    city: str | None = None
    preferred_format: str | None = None
    embedding: list[float] | None = None
    interactions: list[tuple[int, str]] = field(default_factory=list)
    stats: dict[str, tuple[float, float]] = field(default_factory=dict)


class World:
    """Корпус + состояние одного пользователя; общий для всех адаптеров."""

    def __init__(self, events: Sequence[Event], *, now: datetime) -> None:
        self.events = {e.id: e for e in events if e.id is not None}
        self.now = now
        self.user = UserState()

    # ── SearchRepository ─────────────────────────────────────────────────
    def _upcoming(self, event: Event) -> bool:
        return event.start_at is None or event.start_at >= self.now - timedelta(hours=_GRACE_HOURS)

    async def search(self, query: SearchQuery, *, limit: int, now: datetime) -> list[Event]:
        out = []
        for ev in self.events.values():
            if query.date_from or query.date_to:
                if ev.start_at is None:
                    continue
                if query.date_from and ev.start_at < _day(query.date_from):
                    continue
                if query.date_to and ev.start_at > _day(query.date_to, end=True):
                    continue
            elif not self._upcoming(ev):
                continue
            if query.city and ev.city != query.city:
                continue
            if query.event_type and ev.event_type != query.event_type:
                continue
            if query.format and ev.format != query.format:
                continue
            if query.topics and not set(query.topics) & set(ev.topics):
                continue
            text = query.free_text.casefold()
            if text and text not in ev.title.casefold() and text not in ev.description.casefold():
                continue
            out.append(ev)
        far = datetime.max.replace(tzinfo=UTC)
        out.sort(key=lambda e: (e.start_at or far, e.id or 0))
        return out[:limit]

    async def text_search(
        self, query: SearchQuery, text: str, *, limit: int, now: datetime
    ) -> list[Event]:
        """Упрощённый полнотекстовый: число совпавших слов (без морфологии)."""
        terms = {t for t in text.casefold().split() if len(t) > 2}
        scored = []
        for ev in await self.search(query, limit=len(self.events), now=now):
            words = set(f"{ev.title} {ev.description}".casefold().split())
            if hits := len(terms & words):
                scored.append((hits, ev))
        scored.sort(key=lambda x: (-x[0], x[1].id or 0))
        return [ev for _, ev in scored[:limit]]

    async def semantic_search(
        self,
        query: SearchQuery,
        vector: list[float],
        *,
        limit: int,
        now: datetime,
        min_similarity: float,
    ) -> list[Event]:
        scored = [
            (cosine_similarity(vector, ev.embedding), ev)
            for ev in await self.search(query, limit=len(self.events), now=now)
            if ev.embedding is not None
        ]
        scored = [x for x in scored if x[0] >= min_similarity]
        scored.sort(key=lambda x: (-x[0], x[1].id or 0))
        return [ev for _, ev in scored[:limit]]

    async def get_event(self, event_id: int) -> Event | None:
        return self.events.get(event_id)

    async def get_events(self, event_ids: list[int]) -> list[Event]:
        return [self.events[i] for i in event_ids if i in self.events]

    # ── CandidateGenerator ───────────────────────────────────────────────
    async def generate(
        self,
        *,
        user_embedding: list[float] | None,
        city: str | None,
        limit: int,
        now: datetime,
        exclude_interacted_by: int | None = None,
    ) -> list[Event]:
        excluded = (
            {eid for eid, action in self.user.interactions if action in _EXCLUDING}
            if exclude_interacted_by is not None
            else set()
        )
        pool = [e for e in self.events.values() if self._upcoming(e) and e.id not in excluded]
        if user_embedding is not None:
            pool = [e for e in pool if e.embedding is not None]
            pool.sort(key=lambda e: (-cosine_similarity(user_embedding, e.embedding), e.id or 0))
        else:
            pool.sort(key=lambda e: (-(e.quality_score or 0), e.id or 0))
        return pool[:limit]

    # ── аналог accounts UpdateProfile (город/формат) ─────────────────────
    async def execute(
        self, user_id: int, *, city: str | None, preferred_format: str | None
    ) -> Any:
        if city is not None:
            self.user.city = canonicalize_city(city) or None
        if preferred_format is not None:
            self.user.preferred_format = preferred_format or None
        return self.user

    def uow(self) -> WorldUow:
        return WorldUow(self)


class WorldUow:
    """RecommendationUnitOfWork в памяти (изменения применяются сразу)."""

    def __init__(self, world: World) -> None:
        self._w = world

    async def __aenter__(self) -> WorldUow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def get_user_prefs(self, user_id: int) -> UserPrefs:
        u = self._w.user
        return UserPrefs(
            city=u.city,
            preferred_format=u.preferred_format,
            embedding=u.embedding,
            interests=list(u.profile.interests),
            anti_interests=list(u.profile.anti_interests),
        )

    async def load_bayesian_stats(
        self, user_id: int, *, now: datetime, gamma: float
    ) -> BayesianStats:
        return dict(self._w.user.stats)  # диалог короткий — decay несущественен

    async def get_event_topic_codes(self, event_id: int) -> list[str]:
        event = self._w.events.get(event_id)
        return list(event.topics) if event else []

    async def record_interaction(self, user_id: int, event_id: int, action: str) -> None:
        self._w.user.interactions.append((event_id, action))

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
        d_alpha, d_beta = feedback_delta(action, direction)
        for code in topic_codes:
            alpha, beta = self._w.user.stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))
            self._w.user.stats[code] = (
                max(PRIOR_ALPHA, alpha + d_alpha),
                max(PRIOR_BETA, beta + d_beta),
            )

    def _vectors(self, actions: tuple[str, ...]) -> list[list[float]]:
        ids = dict.fromkeys(eid for eid, a in self._w.user.interactions if a in actions)
        return [
            vec
            for eid in ids
            if (vec := getattr(self._w.events.get(eid), "embedding", None)) is not None
        ]

    async def recompute_user_embedding(self, user_id: int) -> None:
        self._w.user.embedding = combine_user_embedding(
            self._w.user.profile.embedding, self._vectors(_POSITIVE), self._vectors(("dislike",))
        )

    async def get_profile(self, user_id: int) -> UserProfile | None:
        return self._w.user.profile

    async def save_profile(self, profile: UserProfile) -> None:
        self._w.user.profile = profile

    async def list_saved(
        self, user_id: int, *, offset: int, limit: int
    ) -> tuple[list[Event], int]:
        saved = list(
            dict.fromkeys(e for e, a in reversed(self._w.user.interactions) if a == "save")
        )
        return [self._w.events[e] for e in saved[offset : offset + limit]], len(saved)

    async def remove_interactions(self, user_id: int, event_id: int, action: str) -> int:
        before = len(self._w.user.interactions)
        self._w.user.interactions = [
            (e, a) for e, a in self._w.user.interactions if not (e == event_id and a == action)
        ]
        return before - len(self._w.user.interactions)

    async def known_topic_codes(self, *, limit: int) -> list[str]:
        counts = Counter(t for e in self._w.events.values() for t in e.topics)
        return [code for code, _ in counts.most_common(limit)]

    async def users_with_positive_feedback_on(
        self, event_ids: list[int], *, limit: int
    ) -> list[int]:
        return []


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class ListJournal:
    def __init__(self) -> None:
        self.turns: list[AgentTurnRecord] = []

    async def record(self, turn: AgentTurnRecord) -> None:
        self.turns.append(turn)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class QueryEmbedding:
    """EmbeddingProvider для профиля (запрос — с query-префиксом энкодера)."""

    def __init__(self, encode: EncodeQuery, dimension: int) -> None:
        self._encode = encode
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_version(self) -> str:
        return "eval"

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [await self._encode(t) for t in texts]

    async def embed_text(self, text: str) -> list[float]:
        return await self._encode(text)


@dataclass
class Stack:
    """Собранные поверх мира use-case'ы приложения."""

    world: World
    agent: AgentTurn
    recommendations: GetRecommendations
    journal: ListJournal
    update_profile: UpdateUserProfile


def build_stack(
    world: World,
    *,
    agent_llm: ToolCallingLLM,
    gateway: LLMGateway,
    embedding: QueryEmbedding,
    config: AgentConfig | None = None,
) -> Stack:
    """Те же классы, что в `interfaces/api/dependencies.py`, но поверх мира в памяти."""
    cfg = config or AgentConfig()
    cache = MemoryCache()
    clock = FixedClock(world.now)
    weights = ScoringWeights()
    uow = world.uow
    recommendations = GetRecommendations(
        uow,
        world,
        HybridRanker(weights),
        cache,
        clock,
        RecommenderConfig(),
        weights,
    )
    nl_search = NlSearch(gateway, world, clock, cache, embedding)
    record = RecordInteraction(uow, cache, clock, weights)
    explain = ExplainEvent(world, uow, gateway, cache, clock, weights)
    apply = ApplyProfileChanges(uow, embedding, cache, clock)
    toolbox = AgentToolbox(
        [
            SearchEventsTool(nl_search),
            RecommendTool(recommendations, world),
            GetEventTool(world),
            ExplainEventTool(explain),
            GetProfileTool(GetUserProfile(uow), uow),
            RecordFeedbackTool(record),
            UpdateProfileTool(apply),
            UpdateSettingsTool(world, cache),  # type: ignore[arg-type]  # аналог accounts UpdateProfile
        ],
        allowed=cfg.allowed_tools,
    )
    journal = ListJournal()
    sessions = AgentSessionStore(
        cache, ttl_seconds=cfg.session_ttl_seconds, history_limit=cfg.history_limit
    )
    agent = AgentTurn(agent_llm, toolbox, sessions, journal, uow, cache, clock, cfg)
    update_profile = UpdateUserProfile(uow, ProfileExtractor(gateway), embedding, cache, clock)
    return Stack(
        world=world,
        agent=agent,
        recommendations=recommendations,
        journal=journal,
        update_profile=update_profile,
    )
