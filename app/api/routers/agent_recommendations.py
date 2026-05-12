from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.db.models.user import User
from app.db.models.event import Event
from app.recommender.user_model import parse_topic_weights
from app.recommender.scoring import _get_user_topic_codes, _get_event_topic_codes
from app.agents.recommendation import recommendation_graph
from app.api.services.recommendation_service import get_recommendations_for_user

router = APIRouter(prefix="/agent-recommendations", tags=["agent-recommendations"])

_MAX_EVENTS_FOR_AGENT = 50


def _build_graph_input(user: User, events: list) -> dict:
    user_profile = {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "topics": list(_get_user_topic_codes(user)),
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topic_weights": parse_topic_weights(user.topic_weights),
    }

    events_data = [
        {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": list(_get_event_topic_codes(event)),
        }
        for event in events
    ]

    return {
        "user_profile": user_profile,
        "events": events_data,
        "user_analysis": "",
        "events_analysis": "",
        "ranked_event_ids": [],
        "ranked_cards": [],
        "final_answer": "",
    }


@router.get("/{telegram_id}")
def get_agent_recommendations(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return {
            "success": False,
            "message": "Профиль пользователя не найден. Сначала настрой профиль через /start."
        }

    events = db.query(Event).limit(_MAX_EVENTS_FOR_AGENT).all()

    try:
        result = recommendation_graph.invoke(_build_graph_input(user, events))
        return {"success": True, "answer": result["final_answer"]}
    except Exception:
        return {"success": False, "message": "AI-сервис временно недоступен."}


@router.get("/{telegram_id}/cards")
def get_agent_recommendation_cards(
    telegram_id: int,
    limit: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return {
            "success": False,
            "message": "Профиль пользователя не найден. Сначала настрой профиль через /start.",
            "cards": [],
        }

    events = db.query(Event).limit(_MAX_EVENTS_FOR_AGENT).all()

    try:
        result = recommendation_graph.invoke(_build_graph_input(user, events))
        cards = result.get("ranked_cards", [])[:limit]

        if cards:
            return {"success": True, "cards": cards}

        raise ValueError("AI returned no cards")

    except Exception:
        # Fallback: scoring-based recommendations
        try:
            recommendations = get_recommendations_for_user(db, telegram_id)
            return {"success": True, "cards": recommendations[:limit]}
        except Exception:
            return {
                "success": False,
                "message": "AI-сервис временно недоступен.",
                "cards": [],
            }
