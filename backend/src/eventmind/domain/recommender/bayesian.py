"""Bayesian (Beta) topic-preference + Thompson sampling. Порт из v1.

Для пары (user, topic) храним Beta(alpha, beta): alpha — успехи (like/save),
beta — неудачи (dislike). При ранжировании сэмплируем p ~ Beta и берём максимум
по темам события (оптимистичная оценка интереса — Thompson по темам-«рукам»).
Temporal-decay применяется лениво при чтении.
"""
from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import datetime

LIKE_WEIGHT = 3.0
SAVE_WEIGHT = 1.0
DISLIKE_WEIGHT = 2.0
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0


def feedback_delta(action: str, direction: int = 1) -> tuple[float, float]:
    """(Δalpha, Δbeta) для действия. direction=-1 — откат (toggle off)."""
    if action == "like":
        return LIKE_WEIGHT * direction, 0.0
    if action == "save":
        return SAVE_WEIGHT * direction, 0.0
    if action == "dislike":
        return 0.0, DISLIKE_WEIGHT * direction
    return 0.0, 0.0


def apply_decay(
    alpha: float, beta: float, updated_at: datetime | None, *, now: datetime, gamma: float = 0.995
) -> tuple[float, float]:
    """Экспоненциально стянуть (α, β) к prior с учётом возраста записи."""
    if updated_at is None or gamma >= 1.0:
        return alpha, beta
    days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    factor = gamma**days
    return (
        PRIOR_ALPHA + max(0.0, alpha - PRIOR_ALPHA) * factor,
        PRIOR_BETA + max(0.0, beta - PRIOR_BETA) * factor,
    )


def apply_feedback(
    alpha: float,
    beta: float,
    updated_at: datetime | None,
    action: str,
    direction: int = 1,
    *,
    now: datetime,
    gamma: float = 0.995,
) -> tuple[float, float]:
    """Новые (α, β) после действия: сначала материализовать decay на момент now.

    Decay применяется лениво при чтении, поэтому в БД лежат «сырые» α/β на
    момент `updated_at`. Прибавлять дельту к сырым значениям нельзя: запись
    сдвигает `updated_at` на now и «воскрешает» весь затухший интерес — один
    дизлайк через год поднимал α с ~5.8 обратно до 31.
    """
    a, b = apply_decay(alpha, beta, updated_at, now=now, gamma=gamma)
    d_alpha, d_beta = feedback_delta(action, direction)
    return max(PRIOR_ALPHA, a + d_alpha), max(PRIOR_BETA, b + d_beta)


def thompson_score(
    stats: dict[str, tuple[float, float]],
    event_topic_codes: Iterable[str],
    *,
    rng: random.Random,
) -> float:
    """Thompson sampling по темам события: max_c Beta(a_c, b_c) ∈ [0, 1]."""
    codes = list(event_topic_codes)
    if not codes:
        return 0.0
    samples = [
        rng.betavariate(*stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))) for code in codes
    ]
    return max(samples)


def posterior_mean(
    stats: dict[str, tuple[float, float]], event_topic_codes: Iterable[str]
) -> float:
    """Детерминированная альтернатива (E[Beta]=a/(a+b)) для эвала/explain."""
    codes = list(event_topic_codes)
    if not codes:
        return 0.0
    means = []
    for code in codes:
        a, b = stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))
        means.append(a / (a + b))
    return max(means)
