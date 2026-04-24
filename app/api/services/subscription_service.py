from sqlalchemy.orm import Session

from app.db.models.user import User


def subscribe_user(db: Session, telegram_id: int) -> dict:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return {
            "success": False,
            "message": "Профиль не найден. Сначала настрой профиль через /start.",
        }

    user.is_subscribed = 1
    db.commit()

    return {
        "success": True,
        "message": "Ты подписался на персональные AI-рекомендации.",
    }


def unsubscribe_user(db: Session, telegram_id: int) -> dict:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        return {
            "success": False,
            "message": "Профиль не найден.",
        }

    user.is_subscribed = 0
    db.commit()

    return {
        "success": True,
        "message": "Подписка на AI-рекомендации отключена.",
    }


def get_subscribed_users(db: Session) -> list[User]:
    return db.query(User).filter(User.is_subscribed == 1).all()