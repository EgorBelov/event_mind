from sqlalchemy.orm import Session

from app.db.models.user import User
from app.api.schemas.user import UserCreate
from app.recommender.user_model import (
    build_initial_topic_weights,
    dump_topic_weights,
    parse_topic_weights,
    sync_topic_weights_with_topics,
)


def create_or_update_user(db: Session, user_data: UserCreate) -> User:
    user = db.query(User).filter(User.telegram_id == user_data.telegram_id).first()

    topics_str = ",".join(user_data.topics)

    if user:
        user.username = user_data.username
        user.preferred_format = user_data.preferred_format
        user.city = user_data.city
        user.topics = topics_str
        current_weights = parse_topic_weights(user.topic_weights)
        synced_weights = sync_topic_weights_with_topics(current_weights, user_data.topics)
        user.topic_weights = dump_topic_weights(synced_weights)
    else:
        user = User(
            telegram_id=user_data.telegram_id,
            username=user_data.username,
            preferred_format=user_data.preferred_format,
            city=user_data.city,
            topics=topics_str,
            topic_weights=dump_topic_weights(
                build_initial_topic_weights(user_data.topics)
            ),
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


def get_user_by_telegram_id(db: Session, telegram_id: int) -> User | None:
    return db.query(User).filter(User.telegram_id == telegram_id).first()
