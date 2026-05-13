from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.schemas.user import UserCreate
from app.api.services.user_service import (
    analyze_bio_and_update_topics,
    create_or_update_user,
    get_user_by_telegram_id,
    get_user_stats,
    get_user_topic_codes,
)
from app.api.services.recommendation_service import refresh_user_embedding

router = APIRouter(prefix="/users", tags=["users"])


class BioPayload(BaseModel):
    bio: str


@router.post("/register")
def register_user(user_data: UserCreate, db: Session = Depends(get_db)):
    user = create_or_update_user(db, user_data)
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topics": get_user_topic_codes(user),
        "topic_weights": user.topic_weights,
    }


@router.get("/{telegram_id}")
def get_user(telegram_id: int, db: Session = Depends(get_db)):
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topics": get_user_topic_codes(user),
        "topic_weights": user.topic_weights,
    }


@router.get("/{telegram_id}/stats")
def get_stats(telegram_id: int, db: Session = Depends(get_db)):
    return get_user_stats(db, telegram_id)


@router.post("/{telegram_id}/analyze-bio")
def analyze_bio(telegram_id: int, payload: BioPayload, db: Session = Depends(get_db)):
    return analyze_bio_and_update_topics(db, telegram_id, payload.bio)


@router.post("/{telegram_id}/update-embedding")
def update_embedding(telegram_id: int, db: Session = Depends(get_db)):
    """Пересчитать и закэшировать персональный embedding пользователя (профиль + история)."""
    from app.db.models.user import User as UserModel
    user = db.query(UserModel).filter(UserModel.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    refresh_user_embedding(db, user)
    db.commit()
    return {"success": True, "message": "Embedding обновлён."}
