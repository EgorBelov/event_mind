"""Контексты скоринга + детерминированные компоненты (cosine/freshness/rule/quality/hype).

Портировано из `legacy/app/recommender/{embeddings,hybrid,scoring}.py`. Чистый
Python (без numpy) — домен лёгкий и без внешних зависимостей.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class UserContext:
    """Профиль пользователя для скоринга."""

    topics: set[str] = field(default_factory=set)
    topic_weights: dict[str, int] = field(default_factory=dict)
    preferred_format: str | None = None
    city: str | None = None
    embedding: list[float] | None = None


@dataclass(slots=True)
class EventFeatures:
    """Признаки события для скоринга."""

    id: int
    topics: list[str] = field(default_factory=list)
    format: str = "unknown"
    city: str = "unknown"
    quality_score: int | None = None
    hype_score: int | None = None
    start_at: datetime | None = None
    embedding: list[float] | None = None
    series_slug: str | None = None


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    """Косинусная близость двух векторов. None/разная длина → 0.0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom < 1e-12:
        return 0.0
    return dot / denom


def freshness_score(
    start_at: datetime | None, *, now: datetime, half_life_days: float = 30.0
) -> float:
    """0..1: 1.0 «сегодня», экспоненциальный decay в обе стороны. None → 0.5."""
    if start_at is None:
        return 0.5
    days = abs((start_at - now).total_seconds()) / 86400.0
    return math.exp(-math.log(2.0) * days / max(half_life_days, 1.0))


def rule_score(user: UserContext, event: EventFeatures) -> float:
    """Rule-based score: веса тем + пересечение + формат + город (порт из v1)."""
    score = 0.0
    event_topics = set(event.topics)
    for topic in event_topics:
        score += user.topic_weights.get(topic, 0)
    common = user.topics & event_topics
    score += len(common) * 2
    if user.preferred_format == "any":
        score += 1
    elif user.preferred_format and user.preferred_format == event.format:
        score += 3
    if user.city == "any" or event.city == "any":
        score += 1
    elif user.city and user.city == event.city:
        score += 2
    return float(score)


def quality_component(event: EventFeatures) -> float:
    """quality_score 1..10 → 0..1 (0 при отсутствии)."""
    q = event.quality_score or 0
    return (q / 10.0) if q > 0 else 0.0


def hype_component(event: EventFeatures) -> float:
    h = event.hype_score or 0
    return (h / 10.0) if h > 0 else 0.0
