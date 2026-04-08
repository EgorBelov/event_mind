from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.user import User
from app.db.models.interaction import Interaction
from app.recommender.scoring import score_event_for_user
from app.recommender.explain import explain_event_for_user
from app.recommender.user_model import (
    parse_topics,
    parse_topic_weights,
    dump_topic_weights,
    apply_feedback_to_weights,
)


def get_recommendations_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return []

    events = db.query(Event).all()
    results = []

    for event in events:
        score = score_event_for_user(user, event)

        results.append({
            "event_id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": list(parse_topics(event.topics)),
            "score": score,
            "explanation": explain_event_for_user(user, event),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def create_interaction(db: Session, telegram_id: int, event_id: int, action: str) -> dict:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "User not found"}

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return {"success": False, "message": "Event not found"}

    changed = False

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
            db.commit()
            return {"success": True, "message": f"Interaction '{action}' removed"}

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
            changed = True

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
            db.commit()
            return {"success": True, "message": "Interaction 'save' removed"}

    interaction = Interaction(
        user_id=user.id,
        event_id=event_id,
        action=action,
    )
    db.add(interaction)

    current_weights = parse_topic_weights(user.topic_weights)
    event_topics = list(parse_topics(event.topics))

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
        return []

    interactions = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id, Interaction.event_id == event_id)
        .all()
    )

    return [item.action for item in interactions]

def get_saved_events_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return []

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
        results.append({
            "event_id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": list(parse_topics(event.topics)),
        })

    return results