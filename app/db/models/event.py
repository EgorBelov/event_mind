from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    format = Column(String, nullable=False)
    city = Column(String, nullable=False)
    level = Column(String, nullable=False)
    date = Column(String, nullable=False)        # человекочитаемая строка для UI
    start_at = Column(DateTime, nullable=True)   # распарсенная дата начала: freshness/сортировка
    event_type = Column(String, nullable=True)
    target_audience = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)       # JSON-вектор
    tech_stack = Column(Text, nullable=True)      # JSON-массив технологий
    seniority = Column(String, nullable=True)     # junior/middle/senior/any
    quality_score = Column(Integer, nullable=True)  # 1-10, оценка качества от AI
    hype_score = Column(Integer, nullable=True)   # 1-10, актуальность темы
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    event_topics = relationship("EventTopic", back_populates="event", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="event", cascade="all, delete-orphan")
