from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.schemas.recommendation import InteractionCreate
from app.api.services.recommendation_service import (
    get_recommendations_for_user,
    create_interaction,
    get_event_interactions_for_user,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{telegram_id}")
def get_recommendations(telegram_id: int, db: Session = Depends(get_db)):
    return get_recommendations_for_user(db, telegram_id)


@router.post("/interactions")
def save_interaction(payload: InteractionCreate, db: Session = Depends(get_db)):
    return create_interaction(
        db=db,
        telegram_id=payload.telegram_id,
        event_id=payload.event_id,
        action=payload.action,
    )


@router.get("/{telegram_id}/event/{event_id}/interactions")
def get_interactions(telegram_id: int, event_id: int, db: Session = Depends(get_db)):
    return {
        "telegram_id": telegram_id,
        "event_id": event_id,
        "actions": get_event_interactions_for_user(db, telegram_id, event_id),
    }