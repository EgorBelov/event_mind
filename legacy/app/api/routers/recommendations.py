from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.recommendation import InteractionCreate
from app.api.services.recommendation_service import (
    advance_feed_cursor,
    create_interaction,
    get_event_interactions_for_user,
    get_feed_cursor,
    get_recommendations_for_user,
    get_saved_events_for_user,
    get_why_explanation_for_user,
    set_feed_cursor,
    undo_last_interaction,
)
from app.db.dependencies import get_db

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{telegram_id}")
def get_recommendations(telegram_id: int, limit: int = 25, db: Session = Depends(get_db)):
    """Top-N рекомендаций. limit<=0 — без ограничения (объяснения всё равно
    строятся только для возвращаемых событий)."""
    return get_recommendations_for_user(db, telegram_id, limit=limit)


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


@router.get("/{telegram_id}/why/{event_id}")
def get_why(telegram_id: int, event_id: int, db: Session = Depends(get_db)):
    """Объяснение «почему рекомендовано»: short (для поп-апа) + full (LLM-нарратив)."""
    return get_why_explanation_for_user(db, telegram_id, event_id)

@router.get("/{telegram_id}/saved")
def get_saved_events(telegram_id: int, db: Session = Depends(get_db)):
    return get_saved_events_for_user(db, telegram_id)


@router.post("/{telegram_id}/undo")
def undo_interaction(telegram_id: int, db: Session = Depends(get_db)):
    """Откатить последнее like/dislike/save пользователя."""
    return undo_last_interaction(db, telegram_id)


# ── Feed cursor (бывший user_recommendation_index в боте) ─────────────────


@router.get("/{telegram_id}/cursor")
def get_cursor(telegram_id: int, db: Session = Depends(get_db)):
    """Текущая позиция пользователя в ленте /recommend."""
    return {"index": get_feed_cursor(db, telegram_id)}


@router.post("/{telegram_id}/cursor/reset")
def reset_cursor(telegram_id: int, db: Session = Depends(get_db)):
    """Сбросить позицию ленты на 0 (вызывается на /recommend и из главного меню)."""
    return {"index": set_feed_cursor(db, telegram_id, 0)}


@router.post("/{telegram_id}/cursor/advance")
def advance_cursor(telegram_id: int, db: Session = Depends(get_db)):
    """Перейти к следующему элементу ленты."""
    return {"index": advance_feed_cursor(db, telegram_id)}