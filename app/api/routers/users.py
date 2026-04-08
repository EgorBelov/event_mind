from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.schemas.user import UserCreate
from app.api.services.user_service import create_or_update_user, get_user_by_telegram_id

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register")
def register_user(user_data: UserCreate, db: Session = Depends(get_db)):
    user = create_or_update_user(db, user_data)
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topics": user.topics.split(",") if user.topics else [],
        "topic_weights": user.topic_weights,
    }


@router.get("/{telegram_id}")
def get_user(telegram_id: int, db: Session = Depends(get_db)):
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        return {"message": "User not found"}

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topics": user.topics.split(",") if user.topics else [],
        "topic_weights": user.topic_weights,
    }