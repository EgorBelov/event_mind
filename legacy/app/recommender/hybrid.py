"""Гибридный multi-objective score: rule + cosine + Bayesian + quality + hype + freshness + skill-gap.

`compute_score_breakdown` возвращает декомпозированный словарь компонентов —
используется в feature-attribution-объяснениях и в `hybrid_score` суммой.

Архитектура:
- Каждая компонента — отдельная функция `_component_*`, возвращающая
  float (вклад) или None (если сигнал недоступен/упал). Это позволяет
  вызывающей стороне отличать «честный 0.0» от «не сработало».
- В словарь breakdown проваленные компоненты складываются как 0.0,
  но в логи уходит причина — это убирает «тихую» гибель сигналов,
  которая раньше прятала баги вроде MMR-NameError.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.utils import utcnow_naive
from app.recommender.bandit import context_vector, load_user_bandit, ucb_score
from app.recommender.bayesian import load_user_stats, thompson_score
from app.recommender.embeddings import (
    blend_user_embedding,
    build_event_embedding,
    build_session_embedding,
    cosine_similarity,
    get_or_build_user_embedding,
)
from app.recommender.gnn import gnn_score
from app.recommender.scoring import _get_event_topic_codes, score_event_for_user
from app.recommender.skill_gap import compute_skill_gap_score

logger = logging.getLogger(__name__)


def _parse_event_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    formats = ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M")
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def freshness_score(event_date: datetime | None, half_life_days: float | None = None) -> float:
    """0..1: 1.0 для события «сегодня», экспоненциальный decay вперёд и назад.

    Прошедшие события — почти 0 (мягко, через тот же decay). Это даёт
    реалистичную просадку без жёсткого фильтра, который ломал бы тесты.
    """
    if event_date is None:
        return 0.5
    half_life = half_life_days or settings.freshness_half_life_days
    now = utcnow_naive()
    days = abs((event_date - now).total_seconds()) / 86400.0
    return float(math.exp(-math.log(2.0) * days / max(half_life, 1.0)))


def _safe_int(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─── Компоненты ─────────────────────────────────────────────────────────


def _component_rule(user, event) -> float | None:
    try:
        return float(score_event_for_user(user, event)) * settings.score_rule_weight
    except Exception as e:
        logger.warning("rule component failed: %s", e)
        return None


def _component_cosine(
    user,
    event,
    db=None,
    precomputed_user_emb: list[float] | None = None,
) -> float | None:
    try:
        if precomputed_user_emb is not None:
            user_emb = precomputed_user_emb
        else:
            user_emb = get_or_build_user_embedding(user)
            if db is not None and getattr(user, "id", None) is not None:
                session_emb = build_session_embedding(db, user, window=5)
                if session_emb is not None:
                    user_emb = blend_user_embedding(user_emb, session_emb, session_weight=0.3)
        raw = getattr(event, "embedding", None)
        event_emb: list[float] | None = None
        if raw:
            try:
                event_emb = json.loads(raw)
            except Exception:
                event_emb = None
        if event_emb is None:
            event_emb = build_event_embedding(event)
        return cosine_similarity(user_emb, event_emb) * settings.score_cosine_weight
    except Exception as e:
        logger.warning("cosine component failed for event=%s: %s", getattr(event, "id", "?"), e)
        return None


def _component_bayesian(
    user,
    event,
    db=None,
    bayesian_stats: dict | None = None,
) -> float | None:
    try:
        stats = bayesian_stats
        if stats is None and db is not None and getattr(user, "id", None) is not None:
            stats = load_user_stats(db, user.id)
        if not stats:
            return 0.0
        event_codes = _get_event_topic_codes(event)
        return thompson_score(stats, event_codes) * settings.score_bayes_weight
    except Exception as e:
        logger.warning("bayesian component failed: %s", e)
        return None


def _component_quality(event) -> float:
    q = _safe_int(getattr(event, "quality_score", None))
    if q <= 0:
        return 0.0
    return (q / 10.0) * settings.score_quality_weight * 10.0


def _component_hype(event) -> float:
    h = _safe_int(getattr(event, "hype_score", None))
    if h <= 0:
        return 0.0
    return (h / 10.0) * settings.score_hype_weight * 10.0


def _component_freshness(event) -> float:
    # Предпочитаем распарсенный start_at (DateTime); если его нет — парсим
    # строковую date на лету (старые записи без backfill).
    ev_dt = getattr(event, "start_at", None) or _parse_event_date(getattr(event, "date", None))
    return freshness_score(ev_dt) * settings.score_freshness_weight


def _component_skill_gap(event, user_skill_profile: dict | None) -> float | None:
    if user_skill_profile is None:
        return 0.0
    try:
        return compute_skill_gap_score(user_skill_profile, event) * settings.score_skill_gap_weight
    except Exception as e:
        logger.warning("skill_gap component failed: %s", e)
        return None


def _component_bandit(
    user,
    event,
    db=None,
    freshness_normalized: float = 0.5,
    bandit_state: tuple | None = None,
) -> float | None:
    if not settings.bandit_enabled:
        return 0.0
    if db is None or getattr(user, "id", None) is None:
        return 0.0
    try:
        x = context_vector(user, event, freshness_normalized)
        if bandit_state is not None:
            A, b = bandit_state
        else:
            A, b = load_user_bandit(db, user.id)
        ucb = ucb_score(A, b, x, alpha=settings.bandit_alpha)
        squashed = 1.0 / (1.0 + math.exp(-ucb))
        return squashed * settings.bandit_weight
    except Exception as e:
        logger.warning("bandit component failed: %s", e)
        return None


def _component_gnn(user, event) -> float | None:
    if not settings.gnn_enabled:
        return 0.0
    try:
        return gnn_score(user, event) * settings.gnn_weight
    except Exception as e:
        logger.warning("gnn component failed: %s", e)
        return None


# ─── Сборка breakdown ────────────────────────────────────────────────────


def compute_score_breakdown(
    user,
    event,
    db=None,
    bayesian_stats: dict | None = None,
    user_skill_profile: dict | None = None,
    *,
    precomputed_user_emb: list[float] | None = None,
    bandit_state: tuple | None = None,
) -> dict[str, float]:
    """Покомпонентный breakdown итогового score.

    Все компоненты возвращают None при сбое — здесь это нормализуется в 0.0.
    Логи о сбоях пишутся уровнем WARNING внутри самих компонентов.
    """
    rule = _component_rule(user, event)
    cosine = _component_cosine(user, event, db=db, precomputed_user_emb=precomputed_user_emb)
    bayesian = _component_bayesian(user, event, db=db, bayesian_stats=bayesian_stats)
    quality = _component_quality(event)
    hype = _component_hype(event)
    freshness = _component_freshness(event)
    skill_gap = _component_skill_gap(event, user_skill_profile)

    fresh_norm = freshness / max(settings.score_freshness_weight, 1e-9)
    bandit = _component_bandit(
        user, event, db=db, freshness_normalized=fresh_norm, bandit_state=bandit_state,
    )
    gnn = _component_gnn(user, event)

    return {
        "rule": rule or 0.0,
        "cosine": cosine or 0.0,
        "bayesian": bayesian or 0.0,
        "quality": quality,
        "hype": hype,
        "freshness": freshness,
        "skill_gap": skill_gap or 0.0,
        "bandit": bandit or 0.0,
        "gnn": gnn or 0.0,
    }


def hybrid_score(
    user,
    event,
    db=None,
    bayesian_stats: dict | None = None,
    user_skill_profile: dict | None = None,
) -> float:
    """Итоговый multi-objective hybrid score — сумма компонентов."""
    breakdown = compute_score_breakdown(
        user, event, db=db, bayesian_stats=bayesian_stats, user_skill_profile=user_skill_profile,
    )
    return float(sum(breakdown.values()))
