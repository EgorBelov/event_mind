from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserTopicStat(Base):
    """Параметры Beta-распределения предпочтения пользователя к теме.

    Каждая строка — (user, topic) с двумя счётчиками:
    - alpha — «успехи» (likes/saves),
    - beta  — «неудачи» (dislikes).

    На каждый feedback альфа/бета увеличиваются (online update).
    При ранжировании сэмплируем p ~ Beta(alpha, beta) — Thompson sampling.
    """
    __tablename__ = "user_topic_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False, index=True)
    alpha = Column(Float, nullable=False, default=1.0)
    beta = Column(Float, nullable=False, default=1.0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_user_topic_stat"),)

    user = relationship("User")
    topic = relationship("Topic")
