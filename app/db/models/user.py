from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    preferred_format = Column(String, nullable=True)
    city = Column(String, nullable=True)
    topic_weights = Column(Text, nullable=True)  # JSON-строка вида {topic_code: int}
    is_subscribed = Column(Integer, default=0)   # 0 / 1
    embedding = Column(Text, nullable=True)      # JSON-вектор персонального embedding'а
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user_topics = relationship("UserTopic", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="user", cascade="all, delete-orphan")
