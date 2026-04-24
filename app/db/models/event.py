from sqlalchemy import Column, Integer, String, Text
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
    topics = Column(String, nullable=False)  # ai_ml,business_analytics
    source_url = Column(String, nullable=True)