from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)   # например, "ai_ml"
    title = Column(String, nullable=False)               # например, "AI / ML"

    # Связи
    user_topics = relationship("UserTopic", back_populates="topic", cascade="all, delete-orphan")
    event_topics = relationship("EventTopic", back_populates="topic", cascade="all, delete-orphan")


class UserTopic(Base):
    __tablename__ = "user_topics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_user_topic"),)

    # Связи
    user = relationship("User", back_populates="user_topics")
    topic = relationship("Topic", back_populates="user_topics")


class EventTopic(Base):
    __tablename__ = "event_topics"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)

    __table_args__ = (UniqueConstraint("event_id", "topic_id", name="uq_event_topic"),)

    # Связи
    event = relationship("Event", back_populates="event_topics")
    topic = relationship("Topic", back_populates="event_topics")
