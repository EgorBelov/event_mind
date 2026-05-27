from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserSkillProfile(Base):
    """Структурированный «карьерный» профиль пользователя, выводимый LLM из bio.

    Хранится отдельной строкой 1:1 к users — чтобы не раздувать users-таблицу
    редко-обновляемыми полями и упростить инвалидацию при перегенерации.
    """
    __tablename__ = "user_skill_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    current_role = Column(String, nullable=True)
    target_role = Column(String, nullable=True)
    seniority = Column(String, nullable=True)           # junior/middle/senior/any
    learning_horizon = Column(String, nullable=True)    # weeks/months/year+

    current_skills = Column(Text, nullable=True)        # JSON-array of skill codes
    target_skills = Column(Text, nullable=True)         # JSON-array of skill codes
    goals = Column(Text, nullable=True)                 # JSON-array short phrases

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")
