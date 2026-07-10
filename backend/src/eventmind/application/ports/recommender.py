"""Порты рекомендера: генерация кандидатов + UoW чтения/обучения."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol

from eventmind.domain.events.entities import Event

BayesianStats = dict[str, tuple[float, float]]


@dataclass(slots=True)
class UserPrefs:
    city: str | None = None
    preferred_format: str | None = None
    embedding: list[float] | None = None


class CandidateGenerator(Protocol):
    """Первая стадия: kNN по user-embedding + фильтры (upcoming/город), топ-N."""

    async def generate(
        self,
        *,
        user_embedding: list[float] | None,
        city: str | None,
        limit: int,
        now: datetime,
    ) -> list[Event]: ...


class RecommendationUnitOfWork(Protocol):
    async def __aenter__(self) -> RecommendationUnitOfWork: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...

    async def get_user_prefs(self, user_id: int) -> UserPrefs | None: ...
    async def load_bayesian_stats(
        self, user_id: int, *, now: datetime, gamma: float
    ) -> BayesianStats: ...
    async def get_event_topic_codes(self, event_id: int) -> list[str]: ...
    async def record_interaction(self, user_id: int, event_id: int, action: str) -> None: ...
    async def apply_feedback_to_stats(
        self, user_id: int, topic_codes: list[str], action: str, direction: int
    ) -> None: ...
    async def recompute_user_embedding(self, user_id: int) -> None: ...


RecommendationUnitOfWorkFactory = Callable[[], RecommendationUnitOfWork]
