from sqlalchemy import Column, Integer, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserBanditState(Base):
    """Состояние LinUCB-бандита на пользователя.

    A — d×d матрица (сериализована как JSON списков),
    b — d-вектор.
    Контекстный вектор x ∈ R^d. Размерность фиксирована
    `LINUCB_DIM` (см. recommender/bandit.py).
    """
    __tablename__ = "user_bandit_states"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    dim = Column(Integer, nullable=False)
    a_json = Column(Text, nullable=False)
    b_json = Column(Text, nullable=False)
    update_count = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")
