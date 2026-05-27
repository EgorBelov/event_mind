from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class RawEvent(Base):
    __tablename__ = "raw_events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    raw_description = Column(Text, nullable=False)
    source_url = Column(String, nullable=True)
    status = Column(String, default="raw", nullable=False)  # raw / normalized / non_it / failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
