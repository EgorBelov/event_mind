"""TTL-кэш рекомендаций пользователя.

Один ряд на telegram_id. items_json — сериализованный список рекомендаций
(тот же формат, что отдаёт `/recommendations`). expires_at рассчитывается
от `recommendation_cache_ttl_minutes` в `app/core/config.py`.
"""
from sqlalchemy import BigInteger, Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from app.db.base import Base


class RecommendationCache(Base):
    __tablename__ = "recommendation_cache"

    telegram_id = Column(BigInteger, primary_key=True)
    items_json = Column(Text, nullable=False)
    limit_used = Column(Integer, nullable=False)
    computed_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
