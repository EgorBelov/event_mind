"""Use-case'ы текстовой модели пользователя: обновить и прочитать профиль.

Поток `UpdateUserProfile`: текст «о себе» → структурный профиль (LLM, вне
транзакции) → эмбеддинг профиля → сохранение → пересчёт users.embedding
(Rocchio: профиль + история) → сброс кэша выдачи. Персональная выдача
появляется сразу, до первого лайка.

Деградация: LLM недоступна — профиль сохраняется со структурой из явных
правок пользователя (или пустой), эмбеддинг всё равно строится по тексту;
провайдер эмбеддингов недоступен — профиль сохраняется без вектора
(рекомендации учтут объявленные интересы через rule-скоринг).
"""
from __future__ import annotations

from collections.abc import Sequence

import structlog

from eventmind.application.ports.cache import Cache
from eventmind.application.ports.embedding import EmbeddingProvider
from eventmind.application.ports.recommender import RecommendationUnitOfWorkFactory
from eventmind.application.ports.security import Clock
from eventmind.application.recommender.profile_extractor import (
    ExtractedProfile,
    ProfileExtractor,
    clean_about,
)
from eventmind.domain.events.taxonomy import slugify_code
from eventmind.domain.recommender.user_model import UserProfile, profile_embedding_text

_logger = structlog.get_logger("eventmind.profile")

_KNOWN_TOPICS_LIMIT = 150
_MANUAL_TOPICS_MAX = 20


def _cache_key(user_id: int) -> str:
    return f"reco:{user_id}"


def _manual_topics(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        slug = slugify_code(v)
        if slug and slug not in out:
            out.append(slug)
    return out[:_MANUAL_TOPICS_MAX]


class UpdateUserProfile:
    def __init__(
        self,
        uow_factory: RecommendationUnitOfWorkFactory,
        extractor: ProfileExtractor,
        embedding: EmbeddingProvider,
        cache: Cache,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._extractor = extractor
        self._embedding = embedding
        self._cache = cache
        self._clock = clock

    async def execute(
        self,
        user_id: int,
        *,
        about: str,
        interests: Sequence[str] | None = None,
        anti_interests: Sequence[str] | None = None,
    ) -> UserProfile:
        """Сохранить профиль. Явные `interests` / `anti_interests` (правки
        пользователя) перекрывают то, что извлекла LLM."""
        about = clean_about(about)
        async with self._uow_factory() as uow:
            known_topics = await uow.known_topic_codes(limit=_KNOWN_TOPICS_LIMIT)

        extracted = await self._extract(about, known_topics)
        anti = (
            _manual_topics(anti_interests)
            if anti_interests is not None
            else extracted.anti_interests
        )
        chosen = _manual_topics(interests) if interests is not None else extracted.interests
        profile = UserProfile(
            user_id=user_id,
            about=about,
            role=extracted.role,
            level=extracted.level,
            stack=extracted.stack,
            interests=[t for t in chosen if t not in anti],
            anti_interests=anti,
            goals=extracted.goals,
            updated_at=self._clock.now(),
        )
        profile.embedding = await self._embed(profile)

        async with self._uow_factory() as uow:
            await uow.save_profile(profile)
            await uow.recompute_user_embedding(user_id)
            await uow.commit()
        await self._cache.delete(_cache_key(user_id))
        return profile

    async def _extract(self, about: str, known_topics: list[str]) -> ExtractedProfile:
        if not about:
            return ExtractedProfile()
        try:
            return await self._extractor.extract(about, known_topics=known_topics)
        except Exception as exc:  # LLM недоступна — профиль без структурной выжимки
            _logger.warning("profile_extract_failed", error=str(exc))
            return ExtractedProfile()

    async def _embed(self, profile: UserProfile) -> list[float] | None:
        text = profile_embedding_text(profile)
        if not text:
            return None
        try:
            return await self._embedding.embed_text(text)
        except Exception as exc:
            _logger.warning("profile_embedding_failed", error=str(exc))
            return None


class GetUserProfile:
    def __init__(self, uow_factory: RecommendationUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, user_id: int) -> UserProfile:
        async with self._uow_factory() as uow:
            profile = await uow.get_profile(user_id)
        return profile or UserProfile(user_id=user_id)
