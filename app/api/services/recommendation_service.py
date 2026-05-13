import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.user import User
from app.db.models.interaction import Interaction
from app.recommender.scoring import score_event_for_user, _get_event_topic_codes
from app.recommender.explain import explain_event_for_user, explain_event_detailed
from app.recommender.user_model import (
    parse_topic_weights,
    dump_topic_weights,
    apply_feedback_to_weights,
)

try:
    from app.recommender.hybrid import hybrid_score as _hybrid_score
    _HAS_HYBRID = True
except Exception:
    _HAS_HYBRID = False


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
    results = []

    for event in events:
        try:
            score = float(_hybrid_score(user, event)) if _HAS_HYBRID else float(score_event_for_user(user, event))
        except Exception:
            score = float(score_event_for_user(user, event))

        explanation = explain_event_detailed(user, event, db=db)

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
            db.commit()
            return {"success": True, "message": "Interaction 'save' removed", "topic_weights": parse_topic_weights(user.topic_weights)}

    db.add(Interaction(user_id=user.id, event_id=event_id, action=action))
    updated_weights = apply_feedback_to_weights(current_weights, event_topics, action)
    user.topic_weights = dump_topic_weights(updated_weights)
    db.commit()

    return {"success": True, "message": f"Interaction '{action}' saved", "topic_weights": updated_weights}


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
