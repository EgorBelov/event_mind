import contextlib
import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.bayesian import update_stats_from_feedback
from app.recommender.explain import explain_event_detailed
from app.recommender.scoring import _get_event_topic_codes, score_event_for_user
from app.recommender.user_model import (
    apply_feedback_to_weights,
    dump_topic_weights,
    parse_topic_weights,
)

logger = logging.getLogger(__name__)

try:
    from app.recommender.hybrid import compute_score_breakdown as _compute_breakdown
    _HAS_HYBRID = True
except Exception:
    _HAS_HYBRID = False
    _compute_breakdown = None  # type: ignore


def refresh_user_embedding(db: Session, user: User) -> None:
    """Посчитать и закэшировать персональный embedding пользователя (best-effort)."""
    try:
        from app.recommender.embeddings import build_rich_user_embedding
        interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
        emb = build_rich_user_embedding(user, interactions)
        user.embedding = json.dumps(emb)
        db.flush()
    except Exception:
        pass


def get_recommendations_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    events = db.query(Event).all()

    # Один раз на запрос: закэшировать вектор пользователя (user.embedding)
    # и досчитать батчем недостающие векторы событий с записью в БД.
    # Иначе hybrid_score/explain пересчитывали эмбеддинги для КАЖДОГО из
    # десятков событий — это и давало ~16 c на список.
    refresh_user_embedding(db, user)
    try:
        from app.recommender.embeddings import ensure_event_embeddings
        ensure_event_embeddings(db, events)
    except Exception:
        pass

    # Bayesian-параметры пользователя — грузим один раз на запрос.
    bayesian_stats = None
    try:
        from app.recommender.bayesian import load_user_stats
        bayesian_stats = load_user_stats(db, user.id)
    except Exception:
        bayesian_stats = None

    # Skill-профиль, если есть — переиспользуется в breakdown.
    try:
        from app.recommender.skill_gap import load_skill_profile
        skill_profile = load_skill_profile(db, user.id)
    except Exception:
        skill_profile = None

    # Precompute user embedding с session-blend — ОДИН раз на запрос,
    # а не на каждое из N событий (раньше build_session_embedding ходил
    # в БД на каждое событие — это ловило timeout на холодном запуске).
    precomputed_user_emb = None
    try:
        from app.recommender.embeddings import (
            blend_user_embedding,
            build_session_embedding,
            get_or_build_user_embedding,
        )
        precomputed_user_emb = get_or_build_user_embedding(user)
        session_emb = build_session_embedding(db, user, window=5)
        if session_emb is not None:
            precomputed_user_emb = blend_user_embedding(
                precomputed_user_emb, session_emb, session_weight=0.3,
            )
    except Exception:
        precomputed_user_emb = None

    # LinUCB-state — один раз на запрос (вместо N SELECT'ов из user_bandit_states).
    bandit_state = None
    if settings.bandit_enabled:
        try:
            from app.recommender.bandit import load_user_bandit
            bandit_state = load_user_bandit(db, user.id)
        except Exception as e:
            logger.warning("LinUCB state load failed for user %s: %s", user.id, e)
            bandit_state = None

    results = []

    for event in events:
        try:
            if _HAS_HYBRID and _compute_breakdown is not None:
                breakdown = _compute_breakdown(
                    user, event, db=db, bayesian_stats=bayesian_stats,
                    user_skill_profile=skill_profile,
                    precomputed_user_emb=precomputed_user_emb,
                    bandit_state=bandit_state,
                )
                score = float(sum(breakdown.values()))
            else:
                breakdown = {}
                score = float(score_event_for_user(user, event))
        except Exception:
            breakdown = {}
            score = float(score_event_for_user(user, event))

        explanation = explain_event_detailed(
            user, event, db=db,
            precomputed_breakdown=breakdown or None,
        )

        results.append({
            "event_id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": list(_get_event_topic_codes(event)),
            "summary": getattr(event, "summary", None),
            "source_url": event.source_url,
            "target_audience": getattr(event, "target_audience", None),
            "tech_stack": _parse_json_field(getattr(event, "tech_stack", None)),
            "seniority": getattr(event, "seniority", None),
            "quality_score": getattr(event, "quality_score", None),
            "hype_score": getattr(event, "hype_score", None),
            "score": round(score, 2),
            "score_breakdown": {k: round(v, 3) for k, v in breakdown.items()},
            "explanation": explanation["text"],
            "explanation_details": {
                "topic_match": explanation["topic_match"],
                "format_match": explanation["format_match"],
                "city_match": explanation["city_match"],
                "semantic_similarity": explanation.get("semantic_similarity"),
                "history_signals": explanation["history_signals"],
            },
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # MMR-диверсификация — пост-процессинг top-N.
    if settings.mmr_enabled and len(results) > 1:
        try:
            from app.recommender.diversity import mmr_rerank
            results = mmr_rerank(results, db, lambda_=settings.mmr_lambda)
        except Exception as e:
            logger.warning("MMR rerank failed: %s", e)

    return results


def _parse_json_field(value) -> list:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def create_interaction(db: Session, telegram_id: int, event_id: int, action: str) -> dict:
    if action not in {"like", "dislike", "save"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    current_weights = parse_topic_weights(user.topic_weights)
    event_topics = _get_event_topic_codes(event)

    if action in {"like", "dislike"}:
        opposite_action = "dislike" if action == "like" else "like"

        existing_same = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == action)
            .first()
        )
        if existing_same:
            db.delete(existing_same)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(current_weights, event_topics, action, direction=-1)
            )
            _safe_bayes_update(db, user.id, event_topics, action, direction=-1)
            _safe_bandit_update(db, user, event, action, direction=-1)
            db.commit()
            return {"success": True, "message": f"Interaction '{action}' removed", "topic_weights": parse_topic_weights(user.topic_weights)}

        existing_opposite = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == opposite_action)
            .first()
        )
        if existing_opposite:
            db.delete(existing_opposite)
            current_weights = apply_feedback_to_weights(current_weights, event_topics, opposite_action, direction=-1)
            _safe_bayes_update(db, user.id, event_topics, opposite_action, direction=-1)
            _safe_bandit_update(db, user, event, opposite_action, direction=-1)

    elif action == "save":
        existing_save = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == "save")
            .first()
        )
        if existing_save:
            db.delete(existing_save)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(current_weights, event_topics, "save", direction=-1)
            )
            _safe_bayes_update(db, user.id, event_topics, "save", direction=-1)
            _safe_bandit_update(db, user, event, "save", direction=-1)
            db.commit()
            return {"success": True, "message": "Interaction 'save' removed", "topic_weights": parse_topic_weights(user.topic_weights)}

    db.add(Interaction(user_id=user.id, event_id=event_id, action=action))
    updated_weights = apply_feedback_to_weights(current_weights, event_topics, action)
    user.topic_weights = dump_topic_weights(updated_weights)
    _safe_bayes_update(db, user.id, event_topics, action, direction=1)
    _safe_bandit_update(db, user, event, action, direction=1)
    _safe_memory_extract(db, user, event, action, direction=1)
    db.commit()

    return {"success": True, "message": f"Interaction '{action}' saved", "topic_weights": updated_weights}


def undo_last_interaction(db: Session, telegram_id: int) -> dict:
    """Откатить самое свежее взаимодействие пользователя.

    Под капотом — повторный create_interaction (toggle off): сама ветка
    «existing_same → delete + direction=-1» уже отменяет all-эффекты
    (веса, Bayesian, LinUCB). Поэтому undo сводится к одному вызову.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    last = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.id.desc())
        .first()
    )
    if not last:
        return {"success": False, "message": "Нет действий для отката."}

    action = last.action
    event_id = last.event_id
    # create_interaction сам выполнит toggle off (delete + direction=-1).
    result = create_interaction(db, telegram_id, event_id, action)
    return {
        "success": True,
        "message": f"Откатил последнее: {action} → event {event_id}.",
        "undone": {"action": action, "event_id": event_id},
        "details": result,
    }


def _safe_bayes_update(db, user_id: int, event_topics, action: str, direction: int = 1) -> None:
    """Best-effort: не падать на feedback'е, если Bayesian-таблица недоступна."""
    with contextlib.suppress(Exception):
        update_stats_from_feedback(db, user_id, event_topics, action, direction=direction)


def _safe_bandit_update(db, user, event, action: str, direction: int = 1) -> None:
    """Best-effort: обновить LinUCB-параметры по feedback."""
    if not settings.bandit_enabled:
        return
    try:
        from app.recommender.bandit import context_vector, reward_from_action, update_from_feedback
        from app.recommender.hybrid import _parse_event_date, freshness_score
        fresh = freshness_score(_parse_event_date(getattr(event, "date", None)))
        x = context_vector(user, event, fresh)
        reward = reward_from_action(action) * direction
        if reward == 0.0:
            return
        update_from_feedback(db, user.id, x, reward)
    except Exception as e:
        logger.warning("LinUCB update failed: %s", e)


def _safe_memory_extract(db, user, event, action: str, direction: int = 1) -> None:
    """Best-effort: long-term memory extract из feedback'а.

    Только для POSITIVE direction — на откат мы ничего не пишем (отдельная
    логика «забыть» не нужна; compaction позже выкинет устаревшее).
    """
    if direction != 1:
        return
    if not getattr(settings, "memory_enabled", True):
        return
    try:
        from app.recommender.memory import extract_from_interaction
        extract_from_interaction(db, user, event, action)
    except Exception as e:
        logger.warning("Memory extract failed: %s", e)


def get_event_interactions_for_user(db: Session, telegram_id: int, event_id: int) -> list[str]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return [
        i.action for i in
        db.query(Interaction).filter(Interaction.user_id == user.id, Interaction.event_id == event_id).all()
    ]


def get_saved_events_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    saved = db.query(Interaction).filter(Interaction.user_id == user.id, Interaction.action == "save").all()
    if not saved:
        return []

    event_ids = [i.event_id for i in saved]
    events = db.query(Event).filter(Event.id.in_(event_ids)).all()

    return [
        {
            "event_id": e.id,
            "title": e.title,
            "description": e.description,
            "format": e.format,
            "city": e.city,
            "level": e.level,
            "date": e.date,
            "topics": list(_get_event_topic_codes(e)),
            "source_url": e.source_url,
        }
        for e in events
    ]
