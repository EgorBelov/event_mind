"""LinUCB contextual bandit поверх Bayesian-предпочтений.

Контекстный вектор x ∈ R^d агрегирует:
- небольшое число тематических индикаторов пользователя (top-K топиков),
- features события (формат-match, city-match, quality/hype нормализованные,
  свежесть, размер пересечения тем).

Размерность намеренно мала (LINUCB_DIM=16), чтобы матрица A=d×d серилизовалась
в БД как JSON в разумные ~2KB и обновлялась без проблем.

Online update (per LinUCB):
    A ← A + x xᵀ
    b ← b + r · x
Прогноз:
    θ̂ = A⁻¹ b
    UCB(x) = xᵀ θ̂ + α · √(xᵀ A⁻¹ x)
"""
from __future__ import annotations

import json
import logging
import math

import numpy as np
from sqlalchemy.orm import Session

from app.db.models.user_bandit_state import UserBanditState
from app.recommender.scoring import _get_event_topic_codes, _get_user_topic_codes

logger = logging.getLogger(__name__)


LINUCB_DIM = 16
LINUCB_ALPHA = 1.0     # exploration coefficient

REWARD_LIKE = 1.0
REWARD_SAVE = 1.5
REWARD_DISLIKE = -1.0


# Фиксированный порядок «слотов» тем в контексте: чтобы при росте/убыли тем
# у одного и того же пользователя контекст оставался стабильно интерпретируемым,
# первые 8 слотов отведём под топ-8 тем из ALLOWED_TOPICS (seed-словарь), а оставшиеся
# 8 — под фичи события и кросс-сигналы.
_SEED_TOPIC_SLOTS = [
    "ai_ml", "data_science", "backend", "frontend",
    "devops", "cybersecurity", "product", "business_analytics",
]
assert len(_SEED_TOPIC_SLOTS) == 8


def _topic_slot_vector(user_codes: set[str], event_codes: set[str]) -> list[float]:
    """Бинарный вектор: 1.0 если тема одновременно у user и event, иначе 0."""
    return [1.0 if (code in user_codes and code in event_codes) else 0.0 for code in _SEED_TOPIC_SLOTS]


def _event_feature_vector(user, event, freshness: float, common_topic_count: int) -> list[float]:
    """8 фич события + кросс-сигналов."""
    fmt_match = 1.0 if user.preferred_format and user.preferred_format == event.format else 0.0
    fmt_any = 1.0 if (user.preferred_format == "any" or getattr(event, "format", None) == "any") else 0.0
    city_match = 1.0 if user.city and user.city == event.city else 0.0
    city_any = 1.0 if (user.city == "any" or getattr(event, "city", None) == "any") else 0.0
    quality = float(event.quality_score or 0) / 10.0
    hype = float(event.hype_score or 0) / 10.0
    common = min(1.0, common_topic_count / 3.0)
    bias = 1.0  # intercept — стабилизирует обучение
    return [fmt_match, fmt_any, city_match, city_any, quality, hype, common, bias]


def context_vector(user, event, freshness: float) -> np.ndarray:
    """Полный 16-мерный контекстный вектор для пары (user, event)."""
    user_codes = _get_user_topic_codes(user)
    event_codes = _get_event_topic_codes(event)
    common = len(user_codes & event_codes)
    return np.array(
        _topic_slot_vector(user_codes, event_codes)
        + _event_feature_vector(user, event, freshness, common),
        dtype=float,
    )


def _new_state(dim: int = LINUCB_DIM) -> tuple[np.ndarray, np.ndarray]:
    A = np.eye(dim)
    b = np.zeros(dim)
    return A, b


def _load_state(db: Session, user_id: int) -> tuple[np.ndarray, np.ndarray, UserBanditState | None]:
    row = db.query(UserBanditState).filter(UserBanditState.user_id == user_id).first()
    if row is None:
        A, b = _new_state()
        return A, b, None
    try:
        A = np.array(json.loads(row.a_json))
        b = np.array(json.loads(row.b_json))
        if A.shape != (LINUCB_DIM, LINUCB_DIM) or b.shape != (LINUCB_DIM,):
            A, b = _new_state()
    except Exception:
        A, b = _new_state()
    return A, b, row


def _save_state(db: Session, user_id: int, A: np.ndarray, b: np.ndarray, row: UserBanditState | None) -> None:
    if row is None:
        row = UserBanditState(
            user_id=user_id, dim=LINUCB_DIM,
            a_json=json.dumps(A.tolist()), b_json=json.dumps(b.tolist()),
            update_count=1,
        )
        db.add(row)
    else:
        row.a_json = json.dumps(A.tolist())
        row.b_json = json.dumps(b.tolist())
        row.update_count = int(row.update_count or 0) + 1
    db.flush()


def update_from_feedback(db: Session, user_id: int, x: np.ndarray, reward: float) -> None:
    """Online LinUCB update: A ← A + xxᵀ; b ← b + r·x."""
    try:
        A, b, row = _load_state(db, user_id)
        A = A + np.outer(x, x)
        b = b + reward * x
        _save_state(db, user_id, A, b, row)
    except Exception as e:
        logger.warning("LinUCB update failed: %s", e)


def ucb_score(A: np.ndarray, b: np.ndarray, x: np.ndarray, alpha: float = LINUCB_ALPHA) -> float:
    """UCB(x) = xᵀ θ̂ + α · sqrt(xᵀ A⁻¹ x)."""
    try:
        A_inv = np.linalg.inv(A)
        theta = A_inv @ b
        mean = float(x @ theta)
        variance = float(x @ A_inv @ x)
        return mean + alpha * math.sqrt(max(variance, 0.0))
    except np.linalg.LinAlgError:
        return 0.0


def load_user_bandit(db: Session, user_id: int) -> tuple[np.ndarray, np.ndarray]:
    """Удобный wrapper для recommendation_service."""
    A, b, _ = _load_state(db, user_id)
    return A, b


def reward_from_action(action: str) -> float:
    return {
        "like": REWARD_LIKE,
        "save": REWARD_SAVE,
        "dislike": REWARD_DISLIKE,
    }.get(action, 0.0)
