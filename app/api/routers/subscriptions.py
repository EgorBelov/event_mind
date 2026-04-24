from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.services.subscription_service import (
    subscribe_user,
    unsubscribe_user,
    get_subscribed_users,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/{telegram_id}/subscribe")
def subscribe(telegram_id: int, db: Session = Depends(get_db)):
    return subscribe_user(db, telegram_id)


@router.post("/{telegram_id}/unsubscribe")
def unsubscribe(telegram_id: int, db: Session = Depends(get_db)):
    return unsubscribe_user(db, telegram_id)


@router.get("/users")
def list_subscribed_users(db: Session = Depends(get_db)):
    users = get_subscribed_users(db)

    return [
        {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "topics": user.topics.split(",") if user.topics else [],
        }
        for user in users
    ]