from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.user import User
from app.db.models.interaction import Interaction
from app.recommender.scoring import score_event_for_user, _get_event_topic_codes
from app.recommender.explain import explain_event_for_user
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


def get_recommendations_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    events = db.query(Event).all()
    results = []

    for event in events:
        try:
            score = float(_hybrid_score(user, event)) if _HAS_HYBRID else float(score_event_for_user(user, event))
        except Exception:
            score = float(score_event_for_user(user, event))

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
            "score": round(score, 2),
            "explanation": explain_event_for_user(user, event, db=db),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def create_interaction(db: Session, telegram_id: int, event_id: int, action: str) -> dict:
    if action not in {"like", "dislike", "save"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported action",
        )

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    current_weights = parse_topic_weights(user.topic_weights)
    event_topics = _get_event_topic_codes(event)

    if action in {"like", "dislike"}:
        opposite_action = "dislike" if action == "like" else "like"

        existing_same = (
            db.query(Interaction)
            .filter(
                Interaction.user_id == user.id,
                Interaction.event_id == event_id,
                Interaction.action == action,
            )
            .first()
        )

        if existing_same:
            db.delete(existing_same)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(
                    current_weights=current_weights,
                    event_topics=event_topics,
                    action=action,
                    direction=-1,
                )
            )
            db.commit()
            return {
                "success": True,
                "message": f"Interaction '{action}' removed",
                "topic_weights": parse_topic_weights(user.topic_weights),
            }

        existing_opposite = (
            db.query(Interaction)
            .filter(
                Interaction.user_id == user.id,
                Interaction.event_id == event_id,
                Interaction.action == opposite_action,
            )
            .first()
        )
        if existing_opposite:
            db.delete(existing_opposite)
            current_weights = apply_feedback_to_weights(
                current_weights=current_weights,
                event_topics=event_topics,
                action=opposite_action,
                direction=-1,
            )

    elif action == "save":
        existing_save = (
            db.query(Interaction)
            .filter(
                Interaction.user_id == user.id,
                Interaction.event_id == event_id,
                Interaction.action == "save",
            )
            .first()
        )

        if existing_save:
            db.delete(existing_save)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(
                    current_weights=current_weights,
                    event_topics=event_topics,
                    action="save",
                    direction=-1,
                )
            )
            db.commit()
            return {
                "success": True,
                "message": "Interaction 'save' removed",
                "topic_weights": parse_topic_weights(user.topic_weights),
            }

    interaction = Interaction(
        user_id=user.id,
        event_id=event_id,
        action=action,
    )
    db.add(interaction)

    updated_weights = apply_feedback_to_weights(
        current_weights=current_weights,
        event_topics=event_topics,
        action=action,
    )
    user.topic_weights = dump_topic_weights(updated_weights)

    db.commit()

    return {
        "success": True,
        "message": f"Interaction '{action}' saved",
        "topic_weights": updated_weights,
    }


def get_event_interactions_for_user(db: Session, telegram_id: int, event_id: int) -> list[str]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    interactions = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id, Interaction.event_id == event_id)
        .all()
    )

    return [item.action for item in interactions]


def get_saved_events_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    saved_interactions = (
        db.query(Interaction)
        .filter(
            Interaction.user_id == user.id,
            Interaction.action == "save",
        )
        .all()
    )

    if not saved_interactions:
        return []

    event_ids = [item.event_id for item in saved_interactions]
    events = db.query(Event).filter(Event.id.in_(event_ids)).all()

    results = []
    for event in events:
        topics = _get_event_topic_codes(event)
        results.append({
            "event_id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": topics,
        })

    return results
