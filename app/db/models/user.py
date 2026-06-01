from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Telegram chat/channel ID легко превышает 2³¹ (особенно отрицательные
    # `-100…` у каналов и супергрупп). BigInt'овая колонка под Postgres,
    # на SQLite фактически тот же INTEGER. См. миграцию f6a7b8c9d0e1.
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    preferred_format = Column(String, nullable=True)
    city = Column(String, nullable=True)
    topic_weights = Column(Text, nullable=True)  # JSON-строка вида {topic_code: int}
    is_subscribed = Column(Integer, default=0)   # 0 / 1
    embedding = Column(Text, nullable=True)      # JSON-вектор персонального embedding'а
    # Курсор по ленте /recommend в боте. Раньше жил module-dict'ом в
    # app/bot/handlers/recommendations.py — терялся при рестарте и не работал
    # под несколькими воркерами. См. миграцию c3d4e5f6a7b8.
    feed_cursor = Column(Integer, nullable=False, server_default="0", default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user_topics = relationship("UserTopic", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="user", cascade="all, delete-orphan")
