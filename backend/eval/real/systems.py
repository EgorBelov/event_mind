"""Сравниваемые системы ранжирования: базовые линии, энкодеры, гибрид.

Все системы получают одно и то же — то, что знает приложение о новом
пользователе без истории (холодный старт): текст «о себе», его выжимку
`ProfileExtractor`, город и формат. Это прямая проверка H1 (семантика против
правил и лексики) и H2 (текстовый профиль закрывает холодный старт).

| система        | что использует                                              |
|----------------|-------------------------------------------------------------|
| random         | ничего (нижняя граница)                                     |
| quality_pop    | quality/hype события — неперсонализированный «топ»          |
| rule           | объявленные интересы/анти-интересы + город/формат (правила) |
| tfidf, bm25    | лексика: текст «о себе» против текста события               |
| emb:<энкодер>  | cosine эмбеддинга профиля и события                         |
| hybrid:<энк.>  | HybridRanker приложения (rule + cosine + quality + ... + MMR)|

Гибрид повторяет двухстадийную схему приложения: кандидаты — top-N по cosine
(как kNN в pgvector; без эмбеддинга — по quality, как cold-start), затем
HybridRanker.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eval.real.data import CorpusEvent, ExtractedPersona, Persona
from eval.real.text import Bm25Index, TfidfIndex
from eventmind.application.ingestion.use_cases import EmbeddingTextMode, event_embedding_text
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.recommender.scoring import (
    EventFeatures,
    UserContext,
    cosine_similarity,
    rule_score,
)
from eventmind.domain.recommender.user_model import (
    UserProfile,
    merge_declared_topics,
    profile_embedding_text,
)
from eventmind.domain.recommender.weights import ScoringWeights


class System(Protocol):
    name: str

    def rank(self, persona: Persona, k: int) -> list[int]: ...


def parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def event_text(ev: CorpusEvent, mode: EmbeddingTextMode = "raw") -> str:
    """Текст события для энкодера; `mode` — эксперимент H4 (raw / summary / both)."""
    return event_embedding_text(ev.title, ev.description, ev.summary, mode=mode)


def persona_profile(persona: Persona, extracted: ExtractedPersona | None) -> UserProfile:
    ex = extracted or ExtractedPersona(id=persona.id)
    return UserProfile(
        user_id=0,
        about=persona.about,
        role=ex.role,
        level=ex.level,
        stack=list(ex.stack),
        interests=list(ex.interests),
        anti_interests=list(ex.anti_interests),
        goals=list(ex.goals),
    )


def persona_text(persona: Persona, extracted: ExtractedPersona | None) -> str:
    """Текст для эмбеддинга персоны — как у пользователя в приложении."""
    return profile_embedding_text(persona_profile(persona, extracted))


def user_context(
    persona: Persona, extracted: ExtractedPersona | None, embedding: list[float] | None
) -> UserContext:
    ex = extracted or ExtractedPersona(id=persona.id)
    weights = merge_declared_topics({}, ex.interests, ex.anti_interests)
    return UserContext(
        topics=set(ex.interests) - set(ex.anti_interests),
        topic_weights=weights,
        preferred_format=persona.preferred_format,
        city=persona.city,
        embedding=embedding,
    )


def event_features(ev: CorpusEvent, embedding: list[float] | None) -> EventFeatures:
    return EventFeatures(
        id=ev.id,
        topics=list(ev.topics),
        format=ev.format,
        city=ev.city,
        quality_score=ev.quality_score,
        hype_score=ev.hype_score,
        start_at=parse_start(ev.start_at),
        embedding=embedding,
        series_slug=ev.series_slug,
    )


def _top(scored: list[tuple[float, int]], k: int) -> list[int]:
    # стабильный tie-break по id — детерминированная выдача
    return [eid for _, eid in sorted(scored, key=lambda x: (-x[0], x[1]))[:k]]


@dataclass(slots=True)
class RandomSystem:
    events: list[CorpusEvent]
    seed: int = 42
    name: str = "random"

    def rank(self, persona: Persona, k: int) -> list[int]:
        ids = [ev.id for ev in self.events]
        random.Random(f"{self.seed}:{persona.id}").shuffle(ids)
        return ids[:k]


@dataclass(slots=True)
class QualityPopSystem:
    events: list[CorpusEvent]
    name: str = "quality_pop"

    def rank(self, persona: Persona, k: int) -> list[int]:
        return _top(
            [((ev.quality_score or 0) + 0.5 * (ev.hype_score or 0), ev.id) for ev in self.events],
            k,
        )


@dataclass(slots=True)
class RuleSystem:
    events: list[CorpusEvent]
    extracted: dict[str, ExtractedPersona]
    name: str = "rule"

    def rank(self, persona: Persona, k: int) -> list[int]:
        ctx = user_context(persona, self.extracted.get(persona.id), None)
        # rule — главный ключ, quality — тай-брейк (иначе ничьи упорядочены случайно)
        return _top(
            [
                (rule_score(ctx, event_features(ev, None)) + 0.01 * (ev.quality_score or 0), ev.id)
                for ev in self.events
            ],
            k,
        )


class LexicalSystem:
    def __init__(self, events: list[CorpusEvent], *, kind: str) -> None:
        self.name = kind
        self._ids = [ev.id for ev in events]
        texts = [event_text(ev) for ev in events]
        self._index: TfidfIndex | Bm25Index = (
            TfidfIndex(texts) if kind == "tfidf" else Bm25Index(texts)
        )

    def rank(self, persona: Persona, k: int) -> list[int]:
        scores = self._index.scores(persona.about)
        return _top(list(zip(scores, self._ids, strict=True)), k)


@dataclass(slots=True)
class EmbeddingSystem:
    name: str
    events: list[CorpusEvent]
    persona_vectors: dict[str, list[float]]
    event_vectors: dict[int, list[float]]

    def rank(self, persona: Persona, k: int) -> list[int]:
        query = self.persona_vectors[persona.id]
        return _top(
            [
                (cosine_similarity(query, self.event_vectors.get(ev.id)), ev.id)
                for ev in self.events
            ],
            k,
        )


@dataclass(slots=True)
class HybridSystem:
    name: str
    events: list[CorpusEvent]
    extracted: dict[str, ExtractedPersona]
    persona_vectors: dict[str, list[float]]
    event_vectors: dict[int, list[float]]
    now: datetime
    mmr: bool = True
    candidate_limit: int = 100  # как RecommenderConfig.candidate_limit

    def _candidates(self, query: list[float] | None) -> list[CorpusEvent]:
        if query is None:
            pool = sorted(self.events, key=lambda ev: (-(ev.quality_score or 0), ev.id))
        else:
            with_vec = [ev for ev in self.events if ev.id in self.event_vectors]
            pool = sorted(
                with_vec,
                key=lambda ev: (-cosine_similarity(query, self.event_vectors[ev.id]), ev.id),
            )
        return pool[: self.candidate_limit]

    def rank(self, persona: Persona, k: int) -> list[int]:
        weights = ScoringWeights()
        if not self.mmr:
            weights = dataclasses.replace(weights, mmr_lambda=1.0)
        query = self.persona_vectors.get(persona.id)
        ctx = user_context(persona, self.extracted.get(persona.id), query)
        features = [
            event_features(ev, self.event_vectors.get(ev.id)) for ev in self._candidates(query)
        ]
        # холодный старт: Bayesian-статов нет → компонента bayesian = 0 (как в приложении)
        ranked = HybridRanker(weights).rank(
            ctx, features, {}, now=self.now, limit=k, rng=random.Random(0)
        )
        return [s.event_id for s in ranked]
