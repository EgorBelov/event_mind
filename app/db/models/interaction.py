from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    action = Column(String, nullable=False)  # like / dislike / save
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Связи
    user = relationship("User", back_populates="interactions")
    event = relationship("Event", back_populates="interactions")
