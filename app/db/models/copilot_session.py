from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class CopilotSession(Base):
    """Сессия многотурового Copilot-разговора с одним пользователем.

    messages_json — JSON-массив объектов {role, content, ts}. Накапливается
    по ходу диалога; при превышении лимита токенов происходит compaction
    (ранние сообщения схлопываются в саммари).
    """
    __tablename__ = "copilot_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    messages_json = Column(Text, nullable=False, default="[]")
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    closed = Column(Integer, default=0)  # 0/1, для архивирования

    user = relationship("User")
