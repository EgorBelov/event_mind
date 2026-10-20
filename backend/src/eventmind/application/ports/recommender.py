"""Порты рекомендера: генерация кандидатов + UoW чтения/обучения."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Protocol

from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.user_model import UserProfile

BayesianStats = dict[str, tuple[float, float]]


@dataclass(slots=True)
class UserPrefs:
    city: str | None = None
    preferred_format: str | None = None
    embedding: list[float] | None = None
    # Из текстового профиля (user_profiles): объявленные интересы/анти-интересы.
    interests: list[str] = field(default_factory=list)
    anti_interests: list[str] = field(default_factory=list)


class CandidateGenerator(Protocol):
    """Первая стадия: kNN по user-embedding + фильтры (upcoming/город), топ-N."""

    async def generate(
        self,
        *,
        user_embedding: list[float] | None,
        city: str | None,
        limit: int,
        now: datetime,
        exclude_interacted_by: int | None = None,
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
        self,
        user_id: int,
        topic_codes: list[str],
        action: str,
        direction: int,
        *,
        now: datetime,
        gamma: float,
    ) -> None: ...
    async def recompute_user_embedding(self, user_id: int) -> None:
        """user.embedding = Rocchio(профиль, like/save, dislike) — см. domain/user_model."""
        ...

    async def get_profile(self, user_id: int) -> UserProfile | None: ...
    async def save_profile(self, profile: UserProfile) -> None: ...
    async def list_saved(
        self, user_id: int, *, offset: int, limit: int
    ) -> tuple[list[Event], int]:
        """Сохранённые события (последние сохранённые — первыми) и их общее число."""
        ...

    async def remove_interactions(self, user_id: int, event_id: int, action: str) -> int:
        """Удалить действия пользователя над событием; вернуть число удалённых."""
        ...

    async def known_topic_codes(self, *, limit: int) -> list[str]:
        """Темы каталога по убыванию числа событий — опора для извлечения профиля."""
        ...
    async def users_with_positive_feedback_on(
        self, event_ids: list[int], *, limit: int
    ) -> list[int]:
        """Пользователи с like/save хотя бы на одно из `event_ids`."""
        ...


RecommendationUnitOfWorkFactory = Callable[[], RecommendationUnitOfWork]
