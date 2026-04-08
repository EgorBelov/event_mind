from sqlalchemy import Column, Integer, String, Text
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    preferred_format = Column(String, nullable=True)
    city = Column(String, nullable=True)
    topics = Column(String, nullable=True)  # ai_ml,data_science
    topic_weights = Column(Text, nullable=True)  # JSON-строка