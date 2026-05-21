"""Гибридный multi-objective score: rule + cosine + Bayesian + quality + hype + freshness + skill-gap.

`compute_score_breakdown` возвращает декомпозированный словарь компонентов —
используется в feature-attribution-объяснениях и в `hybrid_score` суммой.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, date, timezone
from typing import Any

from app.core.config import settings
from app.recommender.scoring import score_event_for_user, _get_event_topic_codes


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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days = abs((event_date - now).total_seconds()) / 86400.0
    # exp(-ln(2) * days / half_life) — классический half-life decay
    return float(math.exp(-math.log(2.0) * days / max(half_life, 1.0)))


def _safe_int(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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

    Все компоненты best-effort: если что-то падает (нет модели, нет БД,
    нет skill-профиля) — соответствующий вклад 0.0.
    """
    out: dict[str, float] = {
        "rule": 0.0,
        "cosine": 0.0,
        "bayesian": 0.0,
        "quality": 0.0,
        "hype": 0.0,
        "freshness": 0.0,
        "skill_gap": 0.0,
        "bandit": 0.0,
        "gnn": 0.0,
    }

    # Rule
    try:
        out["rule"] = float(score_event_for_user(user, event)) * settings.score_rule_weight
    except Exception:
        out["rule"] = 0.0

    # Cosine (с сессионным блендом, если есть db)
    try:
        from app.recommender.embeddings import (
            cosine_similarity,
            get_or_build_user_embedding,
            build_event_embedding,
            build_session_embedding,
            blend_user_embedding,
        )
        # User-emb может быть передан уже посчитанным (см. precomputed_user_emb),
        # чтобы не пересчитывать сессионный bleнд на каждое событие.
        if precomputed_user_emb is not None:
            user_emb = precomputed_user_emb
        else:
            user_emb = get_or_build_user_embedding(user)
            if db is not None and getattr(user, "id", None) is not None:
                session_emb = build_session_embedding(db, user, window=5)
                if session_emb is not None:
                    user_emb = blend_user_embedding(user_emb, session_emb, session_weight=0.3)
        raw = getattr(event, "embedding", None)
        if raw:
            try:
                event_emb = json.loads(raw)
            except Exception:
                event_emb = build_event_embedding(event)
        else:
            event_emb = build_event_embedding(event)
        out["cosine"] = cosine_similarity(user_emb, event_emb) * settings.score_cosine_weight
    except Exception:
        out["cosine"] = 0.0

    # Bayesian (Thompson)
    try:
        from app.recommender.bayesian import load_user_stats, thompson_score
        stats = bayesian_stats
        if stats is None and db is not None and getattr(user, "id", None) is not None:
            stats = load_user_stats(db, user.id)
        if stats:
            event_codes = _get_event_topic_codes(event)
            out["bayesian"] = thompson_score(stats, event_codes) * settings.score_bayes_weight
    except Exception:
        out["bayesian"] = 0.0

    # Quality (1..10 → нормализовано 0..1, помножено на вес)
    q = _safe_int(getattr(event, "quality_score", None))
    if q > 0:
        out["quality"] = (q / 10.0) * settings.score_quality_weight * 10.0  # max +5 при weight=0.5

    # Hype (аналогично)
    h = _safe_int(getattr(event, "hype_score", None))
    if h > 0:
        out["hype"] = (h / 10.0) * settings.score_hype_weight * 10.0

    # Freshness
    ev_dt = _parse_event_date(getattr(event, "date", None))
    out["freshness"] = freshness_score(ev_dt) * settings.score_freshness_weight

    # Skill-gap (если профиль скиллов есть)
    if user_skill_profile is not None:
        try:
            from app.recommender.skill_gap import compute_skill_gap_score
            out["skill_gap"] = (
                compute_skill_gap_score(user_skill_profile, event)
                * settings.score_skill_gap_weight
            )
        except Exception:
            out["skill_gap"] = 0.0

    # LinUCB bandit
    if settings.bandit_enabled and db is not None and getattr(user, "id", None) is not None:
        try:
            from app.recommender.bandit import context_vector, ucb_score, load_user_bandit
            fresh = out["freshness"] / max(settings.score_freshness_weight, 1e-9)
            x = context_vector(user, event, fresh)
            # Принимаем заранее загруженное (A, b), если есть — экономия N
            # отдельных SELECT'ов из user_bandit_states.
            if bandit_state is not None:
                A, b = bandit_state
            else:
                A, b = load_user_bandit(db, user.id)
            ucb = ucb_score(A, b, x, alpha=settings.bandit_alpha)
            # Сжимаем сигмоидой в [0..1] для стабильности.
            squashed = 1.0 / (1.0 + math.exp(-ucb))
            out["bandit"] = squashed * settings.bandit_weight
        except Exception:
            out["bandit"] = 0.0

    # GNN embedding (best-effort)
    if settings.gnn_enabled:
        try:
            from app.recommender.gnn import gnn_score
            out["gnn"] = gnn_score(user, event) * settings.gnn_weight
        except Exception:
            out["gnn"] = 0.0

    return out


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
