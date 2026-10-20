"""Модель пользователя: текстовый профиль + смешивание векторов (Rocchio).

Профиль — то, что пользователь рассказал о себе свободным текстом, и его
структурная выжимка (роль, уровень, стек, интересы, анти-интересы, цели;
извлекает LLM в application-слое). Из профиля строится эмбеддинг, который
закрывает холодный старт: персональная выдача есть ещё до первого лайка.

Итоговый эмбеддинг пользователя (для kNN-кандидатов и cosine-скоринга) —
классическая формула Rocchio:

    u = a·p̂ + b·mean(pos)^ − c·mean(neg)^,   затем нормировка,

где p — эмбеддинг профиля, pos/neg — эмбеддинги событий с like/save и dislike,
^ — единичный вектор. Объявленные интересы и анти-интересы дополнительно
попадают в rule-скоринг (`merge_declared_topics`).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

# Вес объявленного интереса в rule-скоринге (сопоставим с парой лайков темы)
# и штраф анти-интереса (перекрывает и объявленный, и выученный интерес).
DECLARED_INTEREST_WEIGHT = 3
ANTI_INTEREST_PENALTY = 6


@dataclass(slots=True)
class UserProfile:
    user_id: int
    about: str = ""
    role: str = ""
    level: str = "any"  # junior | middle | senior | any
    stack: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)  # topic-slug'и
    anti_interests: list[str] = field(default_factory=list)  # topic-slug'и
    goals: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    updated_at: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not (
            self.about.strip() or self.role or self.stack or self.interests or self.goals
        )


def profile_embedding_text(profile: UserProfile) -> str:
    """Текст, по которому строится эмбеддинг профиля.

    Анти-интересы сюда не входят: вектор профиля должен тянуть к интересному,
    а отталкивание от неинтересного делает rule-штраф.
    """
    parts: list[str] = []
    if profile.role:
        parts.append(f"Роль: {profile.role}")
    if profile.level and profile.level != "any":
        parts.append(f"Уровень: {profile.level}")
    if profile.stack:
        parts.append("Стек: " + ", ".join(profile.stack))
    if profile.interests:
        parts.append("Интересы: " + ", ".join(profile.interests))
    if profile.goals:
        parts.append("Цели: " + "; ".join(profile.goals))
    if profile.about.strip():
        parts.append(profile.about.strip())
    return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class RocchioWeights:
    """Веса Rocchio (классические α=1, β=0.75, γ=0.15)."""

    profile: float = 1.0
    positive: float = 0.75
    negative: float = 0.15


def _unit(vec: Sequence[float]) -> list[float] | None:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return None
    return [x / norm for x in vec]


def _mean_unit(vectors: Sequence[Sequence[float]], dim: int) -> list[float] | None:
    same_dim = [v for v in vectors if len(v) == dim]
    if not same_dim:
        return None
    mean = [sum(v[i] for v in same_dim) / len(same_dim) for i in range(dim)]
    return _unit(mean)


def combine_user_embedding(
    profile: Sequence[float] | None,
    positives: Sequence[Sequence[float]],
    negatives: Sequence[Sequence[float]],
    weights: RocchioWeights | None = None,
) -> list[float] | None:
    """Эмбеддинг пользователя по Rocchio; None — нет ни профиля, ни позитивов.

    Одни дизлайки вектор не задают: «направление от неинтересного» для
    kNN-поиска бессмысленно — такой пользователь остаётся на cold-start.
    """
    w = weights or RocchioWeights()
    reference = profile if profile else (positives[0] if positives else None)
    if not reference:
        return None
    dim = len(reference)

    terms: list[tuple[float, list[float] | None]] = [
        (w.profile, _unit(profile) if profile and len(profile) == dim else None),
        (w.positive, _mean_unit(positives, dim)),
    ]
    if all(vec is None for _, vec in terms):
        return None
    terms.append((-w.negative, _mean_unit(negatives, dim)))

    combined = [0.0] * dim
    for weight, vec in terms:
        if vec is None:
            continue
        for i, x in enumerate(vec):
            combined[i] += weight * x
    return _unit(combined)


def merge_declared_topics(
    learned: dict[str, int], interests: Sequence[str], anti_interests: Sequence[str]
) -> dict[str, int]:
    """Веса тем для rule-скоринга: выученные (Bayesian) + объявленные в профиле.

    Объявленный интерес даёт минимум `DECLARED_INTEREST_WEIGHT`; анти-интерес —
    штраф `-ANTI_INTEREST_PENALTY`, перекрывающий любой положительный вес.
    """
    weights = dict(learned)
    for code in interests:
        weights[code] = max(weights.get(code, 0), DECLARED_INTEREST_WEIGHT)
    for code in anti_interests:
        weights[code] = -ANTI_INTEREST_PENALTY
    return weights
