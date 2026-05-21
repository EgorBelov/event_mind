"""Bayesian (Beta) topic preference + Thompson sampling.

Для каждой пары (user, topic) храним параметры Beta-распределения:
- alpha — успехи (like/save с весом),
- beta  — неудачи (dislike).

Каждый feedback обновляет alpha/beta в БД. При ранжировании событий
сэмплируем p_topic ~ Beta(alpha, beta) и берём максимум по темам события
как Bayesian-score (Thompson sampling по темам-«рукам»).
"""
import random
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.topic import Topic
from app.db.models.user_topic_stat import UserTopicStat


LIKE_WEIGHT = 3.0
SAVE_WEIGHT = 1.0
DISLIKE_WEIGHT = 2.0

PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0


def _apply_decay(alpha: float, beta: float, updated_at: datetime | None) -> tuple[float, float]:
    """Экспоненциально стянуть (α, β) к prior с учётом возраста записи.

    Формула: posterior_evidence = (alpha − prior_alpha) * γ^days_since.
    Это сохраняет prior как «дно» и плавно «забывает» давний feedback.
    """
    if updated_at is None:
        return alpha, beta
    gamma = settings.bayes_decay_per_day
    if gamma >= 1.0:
        return alpha, beta
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    except Exception:
        return alpha, beta
    factor = gamma ** days
    decayed_alpha = PRIOR_ALPHA + max(0.0, alpha - PRIOR_ALPHA) * factor
    decayed_beta = PRIOR_BETA + max(0.0, beta - PRIOR_BETA) * factor
    return decayed_alpha, decayed_beta


def _get_or_create_stat(db: Session, user_id: int, topic_id: int) -> UserTopicStat:
    stat = (
        db.query(UserTopicStat)
        .filter(UserTopicStat.user_id == user_id, UserTopicStat.topic_id == topic_id)
        .first()
    )
    if stat is None:
        stat = UserTopicStat(
            user_id=user_id,
            topic_id=topic_id,
            alpha=PRIOR_ALPHA,
            beta=PRIOR_BETA,
        )
        db.add(stat)
        db.flush()
    return stat


def update_stats_from_feedback(
    db: Session,
    user_id: int,
    event_topic_codes: Iterable[str],
    action: str,
    direction: int = 1,
) -> None:
    """Online-обновление Beta-параметров по одному feedback'у.

    direction=+1 — feedback применяется, -1 — откат (toggle off).
    """
    codes = list(event_topic_codes)
    if not codes:
        return

    topics = db.query(Topic).filter(Topic.code.in_(codes)).all()
    if not topics:
        return

    if action == "like":
        d_alpha, d_beta = LIKE_WEIGHT * direction, 0.0
    elif action == "save":
        d_alpha, d_beta = SAVE_WEIGHT * direction, 0.0
    elif action == "dislike":
        d_alpha, d_beta = 0.0, DISLIKE_WEIGHT * direction
    else:
        return

    for t in topics:
        stat = _get_or_create_stat(db, user_id, t.id)
        stat.alpha = max(PRIOR_ALPHA, stat.alpha + d_alpha)
        stat.beta = max(PRIOR_BETA, stat.beta + d_beta)


def load_user_stats(db: Session, user_id: int) -> dict[str, tuple[float, float]]:
    """Вернуть {topic_code: (alpha, beta)} с учётом temporal decay.

    Decay применяется **лениво** при чтении: в БД хранится «сырое»
    накопленное (α, β), а здесь оно ослабляется в зависимости от
    `updated_at`. Это даёт правильное поведение без отдельного nightly job.
    """
    rows = (
        db.query(UserTopicStat, Topic)
        .join(Topic, UserTopicStat.topic_id == Topic.id)
        .filter(UserTopicStat.user_id == user_id)
        .all()
    )
    out: dict[str, tuple[float, float]] = {}
    for stat, topic in rows:
        a, b = _apply_decay(stat.alpha, stat.beta, stat.updated_at)
        out[topic.code] = (a, b)
    return out


def thompson_score(
    stats: dict[str, tuple[float, float]],
    event_topic_codes: Iterable[str],
    rng: random.Random | None = None,
) -> float:
    """Thompson sampling по темам события.

    Для каждой темы события сэмплируем p ~ Beta(alpha, beta) и берём максимум:
    это «оптимистичная» оценка интереса пользователя к самой подходящей теме.
    Возвращает значение в [0, 1].
    """
    codes = list(event_topic_codes)
    if not codes:
        return 0.0
    r = rng or random
    samples: list[float] = []
    for code in codes:
        alpha, beta = stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))
        samples.append(r.betavariate(alpha, beta))
    return max(samples)


def posterior_mean(
    stats: dict[str, tuple[float, float]],
    event_topic_codes: Iterable[str],
) -> float:
    """Детерминированная альтернатива Thompson для офлайн-эвала и explain.

    Возвращает максимум по темам события: E[Beta(a,b)] = a / (a + b).
    """
    codes = list(event_topic_codes)
    if not codes:
        return 0.0
    means: list[float] = []
    for code in codes:
        alpha, beta = stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))
        means.append(alpha / (alpha + beta))
    return max(means)
