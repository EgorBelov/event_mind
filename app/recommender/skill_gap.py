"""Skill-gap scoring: насколько событие приближает пользователя к цели.

Логика:
1) Если у пользователя есть `target_skills` (или `target_role` → выводимые из него
   tech_stack-ассоциации) и у события есть `tech_stack` — пересечение даёт сигнал
   "это событие приближает к цели".
2) Бонус за совпадение seniority (тренируемся на своём уровне, но и чуть выше).

Возвращает 0..1. Если данных нет — 0.0.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.user_skill_profile import UserSkillProfile


logger = logging.getLogger(__name__)


# Эвристическое сопоставление целевая_роль → ожидаемый tech_stack.
# Используется, когда LLM не вернул target_skills явно.
_ROLE_TO_SKILLS: dict[str, list[str]] = {
    "ml_engineer": ["python", "pytorch", "tensorflow", "sklearn", "mlops"],
    "data_scientist": ["python", "pandas", "sklearn", "sql", "statistics"],
    "backend_developer": ["python", "fastapi", "django", "postgres", "redis"],
    "frontend_developer": ["typescript", "react", "vue", "nextjs"],
    "devops_engineer": ["kubernetes", "docker", "terraform", "ci/cd", "helm"],
    "data_engineer": ["spark", "airflow", "kafka", "sql", "dbt"],
    "security_engineer": ["pentest", "owasp", "iam", "burp"],
    "product_manager": ["product", "analytics", "discovery"],
}


def _norm_skill(s: str) -> str:
    return (s or "").strip().lower()


def upsert_skill_profile(db: Session, user_id: int, bio_profile) -> UserSkillProfile:
    """Создать/обновить UserSkillProfile из BioProfile (см. cold_start.py).

    Принимает pydantic-объект с полями: topics, priority_topics, seniority, goals.
    Угадывает target_role из priority_topics + goals (мягкая эвристика).
    """
    row = db.query(UserSkillProfile).filter(UserSkillProfile.user_id == user_id).first()
    if row is None:
        row = UserSkillProfile(user_id=user_id)
        db.add(row)

    # Угадаем target_role из priority_topics (первый приоритет → mapping).
    target_role = None
    if bio_profile.priority_topics:
        topic = bio_profile.priority_topics[0]
        mapping = {
            "ai_ml": "ml_engineer",
            "data_science": "data_scientist",
            "business_analytics": "data_scientist",
            "backend": "backend_developer",
            "frontend": "frontend_developer",
            "devops": "devops_engineer",
            "cybersecurity": "security_engineer",
            "product": "product_manager",
        }
        target_role = mapping.get(topic)

    target_skills = _ROLE_TO_SKILLS.get(target_role or "", [])
    # Берём топики как «текущие интересы» в качестве proxy current_skills.
    current_skills = list(bio_profile.topics)

    row.seniority = bio_profile.seniority
    row.target_role = target_role
    row.current_skills = json.dumps(current_skills, ensure_ascii=False)
    row.target_skills = json.dumps(target_skills, ensure_ascii=False)
    row.goals = json.dumps(bio_profile.goals or [], ensure_ascii=False)
    db.flush()
    return row


def load_skill_profile(db: Session, user_id: int) -> dict[str, Any] | None:
    """Вернуть dict с полями профиля или None если профиля нет."""
    row = db.query(UserSkillProfile).filter(UserSkillProfile.user_id == user_id).first()
    if row is None:
        return None

    def _decode(v):
        if not v:
            return []
        try:
            return json.loads(v)
        except Exception:
            return []

    return {
        "current_role": row.current_role,
        "target_role": row.target_role,
        "seniority": row.seniority,
        "current_skills": _decode(row.current_skills),
        "target_skills": _decode(row.target_skills),
        "goals": _decode(row.goals),
    }


def compute_skill_gap_score(profile: dict[str, Any] | None, event) -> float:
    """Вернуть 0..1: насколько event приближает пользователя к target."""
    if not profile:
        return 0.0
    target = {_norm_skill(s) for s in (profile.get("target_skills") or [])}
    if not target:
        return 0.0

    # tech_stack события — JSON-массив строк.
    raw = getattr(event, "tech_stack", None)
    if not raw:
        return 0.0
    try:
        stack = json.loads(raw)
    except Exception:
        return 0.0
    event_skills = {_norm_skill(s) for s in stack if s}
    if not event_skills:
        return 0.0

    overlap = target & event_skills
    if not overlap:
        return 0.0

    # Доля target-скиллов, которые событие покрывает.
    coverage = len(overlap) / max(1, len(target))

    # Бонус +0.1 если seniority события == seniority юзера (или 'any').
    user_sen = (profile.get("seniority") or "").lower()
    ev_sen = (getattr(event, "seniority", None) or "").lower()
    if user_sen and ev_sen and (user_sen == ev_sen or ev_sen == "any"):
        coverage = min(1.0, coverage + 0.1)

    return float(coverage)
