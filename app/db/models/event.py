from sqlalchemy import Column, Integer, String, Text, DateTime
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
    date = Column(String, nullable=False)
    event_type = Column(String, nullable=True)
    target_audience = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    event_topics = relationship("EventTopic", back_populates="event", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="event", cascade="all, delete-orphan")
