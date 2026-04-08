from sqlalchemy import Column, Integer, String
from app.db.base import Base


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    event_id = Column(Integer, nullable=False, index=True)
    action = Column(String, nullable=False)  # like / dislike / save