from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.recommender.scoring import _get_user_topic_codes, _get_event_topic_codes
from app.recommender.user_model import parse_topic_weights
from app.api.services.recommendation_service import get_recommendations_for_user

router = APIRouter(prefix="/copilot", tags=["copilot"])

_MAX_EVENTS = 50


class CopilotRequest(BaseModel):
    goal: str


@router.post("/{telegram_id}")
def copilot(
    telegram_id: int,
    payload: CopilotRequest,
    limit: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """AI Event Copilot: разобрать цель пользователя и предложить релевантные события с roadmap."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "Профиль не найден. Сначала настрой профиль через /start."}

    events = db.query(Event).limit(_MAX_EVENTS).all()

    user_profile = {
        "topics": list(_get_user_topic_codes(user)),
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topic_weights": parse_topic_weights(user.topic_weights),
    }

    events_data = [
        {
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "format": e.format,
            "city": e.city,
            "level": e.level,
            "date": e.date,
            "topics": list(_get_event_topic_codes(e)),
        }
        for e in events
    ]

    interaction_summary = _build_interaction_summary(db, user)

    try:
        from app.agents.copilot.agent import copilot_graph

        result = copilot_graph.invoke({
            "goal": payload.goal,
            "user_profile": user_profile,
            "events": events_data,
            "interaction_summary": interaction_summary,
            "answer": "",
            "recommended_event_ids": [],
        })

        # Обогащаем карточки рекомендованных событий
        recommended_ids = result.get("recommended_event_ids", [])[:limit]
        events_by_id = {e.id: e for e in events}
        cards = [
            {
                "event_id": eid,
                "title": events_by_id[eid].title,
                "format": events_by_id[eid].format,
                "city": events_by_id[eid].city,
                "date": events_by_id[eid].date,
                "topics": list(_get_event_topic_codes(events_by_id[eid])),
                "source_url": events_by_id[eid].source_url,
            }
            for eid in recommended_ids
            if eid in events_by_id
        ]

        return {
            "success": True,
            "answer": result["answer"],
            "cards": cards,
        }

    except Exception:
        # Fallback: rule-based рекомендации + пометка про цель
        try:
            recs = get_recommendations_for_user(db, telegram_id)[:limit]
            return {
                "success": True,
                "answer": f"Подобрал события по твоему профилю (AI-помощник временно недоступен).",
                "cards": recs,
            }
        except Exception:
            return {"success": False, "message": "Copilot временно недоступен."}


def _build_interaction_summary(db: Session, user: User) -> str:
    interactions = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.id.desc())
        .limit(10)
        .all()
    )
    if not interactions:
        return "нет истории"

    liked = sum(1 for i in interactions if i.action == "like")
    saved = sum(1 for i in interactions if i.action == "save")
    disliked = sum(1 for i in interactions if i.action == "dislike")
    return f"последние 10: лайков {liked}, сохранений {saved}, дизлайков {disliked}"
