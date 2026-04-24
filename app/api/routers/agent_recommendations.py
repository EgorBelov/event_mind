from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.db.models.user import User
from app.db.models.event import Event
from app.recommender.user_model import parse_topics, parse_topic_weights
from app.agents.recommendation import recommendation_graph

router = APIRouter(prefix="/agent-recommendations", tags=["agent-recommendations"])


@router.get("/{telegram_id}")
def get_agent_recommendations(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return {
            "success": False,
            "message": "Профиль пользователя не найден. Сначала настрой профиль через /start."
        }

    events = db.query(Event).all()

    user_profile = {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "topics": list(parse_topics(user.topics)),
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
            "topics": list(parse_topics(event.topics)),
        }
        for event in events
    ]

    result = recommendation_graph.invoke({
        "user_profile": user_profile,
        "events": events_data,
        "user_analysis": "",
        "events_analysis": "",
        "ranked_events": "",
        "final_answer": "",
    })

    return {
        "success": True,
        "answer": result["final_answer"],
    }