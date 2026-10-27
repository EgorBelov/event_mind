"""Объяснение «почему рекомендовано» — детерминированно, по тем же признакам,
что использует ранкер (темы, семантическая близость, формат, город, качество,
дата). LLM здесь не участвует: причины не выдумываются, а выводятся из модели
пользователя и признаков события.

Два уровня (P1 №11):
- `explain_match` — человеческие причины («темы из ваших интересов: Go»);
- `contributions` — вклад каждой компоненты гибридного скоринга в итоговый
  балл события (доля от суммы модулей): то, что реально подняло событие.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from eventmind.domain.events.taxonomy import city_label, topic_title
from eventmind.domain.recommender.scoring import EventFeatures, UserContext, cosine_similarity

# Пороги близости для мультиязычных sentence-энкодеров (MiniLM даёт ~0.2–0.7
# на релевантных парах) — эвристика для формулировки, не для ранжирования.
VERY_CLOSE = 0.6
CLOSE = 0.4
HIGH_QUALITY = 8
SOON_DAYS = 14


def _titles(codes: set[str]) -> str:
    return ", ".join(topic_title(c) for c in sorted(codes))


def explain_match(user: UserContext, event: EventFeatures, *, now: datetime) -> list[str]:
    reasons: list[str] = []
    event_topics = set(event.topics)

    common = user.topics & event_topics
    if common:
        reasons.append(f"Темы из ваших интересов: {_titles(common)}")
    disliked = {t for t in event_topics if user.topic_weights.get(t, 0) < 0}
    if disliked:
        reasons.append(f"Есть тема из «не интересно»: {_titles(disliked)}")

    if user.embedding and event.embedding:
        sim = cosine_similarity(user.embedding, event.embedding)
        if sim >= VERY_CLOSE:
            reasons.append("Очень близко по смыслу к вашему профилю и оценкам")
        elif sim >= CLOSE:
            reasons.append("Близко по смыслу к вашему профилю и оценкам")

    if user.preferred_format and user.preferred_format == event.format:
        reasons.append(f"Подходящий формат: {event.format}")
    if user.city and user.city not in ("any", "unknown") and user.city == event.city:
        reasons.append(f"В вашем городе: {city_label(event.city)}")
    if event.quality_score is not None and event.quality_score >= HIGH_QUALITY:
        reasons.append(f"Высокая информативность ({event.quality_score}/10)")
    if event.start_at is not None:
        days = (event.start_at - now).days
        if 0 <= days <= SOON_DAYS:
            reasons.append("Уже сегодня" if days == 0 else f"Скоро: через {days} дн.")

    if not reasons or (len(reasons) == 1 and disliked):
        reasons.append(
            "Подобрано по общей популярности и свежести — расскажите о себе, "
            "чтобы подбор был точнее"
        )
    return reasons


COMPONENT_LABELS: dict[str, str] = {
    "cosine": "смысл",  # близость эмбеддингов профиля/оценок и события
    "rule": "темы, формат, город",
    "bayesian": "ваши оценки",
    "quality": "качество",
    "hype": "актуальность",
    "freshness": "дата",
}


@dataclass(frozen=True, slots=True)
class Contribution:
    component: str
    label: str
    value: float  # вклад в балл (со знаком: анти-интерес даёт минус)
    share: float  # |value| / Σ|value|, 0..1


def contributions(breakdown: Mapping[str, float]) -> list[Contribution]:
    """Вклады компонент по убыванию модуля; нулевые отброшены."""
    nonzero = {k: v for k, v in breakdown.items() if abs(v) > 1e-9}
    total = sum(abs(v) for v in nonzero.values())
    if total <= 0:
        return []
    return [
        Contribution(
            component=name,
            label=COMPONENT_LABELS.get(name, name),
            value=round(value, 4),
            share=round(abs(value) / total, 4),
        )
        for name, value in sorted(nonzero.items(), key=lambda kv: (-abs(kv[1]), kv[0]))
    ]
