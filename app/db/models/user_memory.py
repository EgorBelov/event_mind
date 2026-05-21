from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserMemory(Base):
    """Долговременная память о пользователе в стиле mem0.

    В отличие от passive store (`User.topic_weights`, `Interaction`), это —
    структурированные заметки от первого лица о вкусах, целях, ограничениях:
        «пользователь хочет перейти в ML в течение 6 месяцев»
        «активно сохраняет события про Kubernetes»
        «отказывается от offline-формата в Москве».

    Заметки порождаются:
    - LLM-извлечением из feedback'а (лайк/дизлайк/сейв в `extract_from_interaction`),
    - LLM-извлечением из Copilot-диалога (`extract_from_dialog` после каждого turn),
    - cold-start bootstrap'ом из bio.

    Используются специалистами Copilot'а через tool `recall_about_user(query)`.
    Периодически уплотняются (`compact_user_memories`) при росте.
    """
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    # interest / dislike / goal / constraint / context / event_pref / other
    salience = Column(Float, nullable=False, default=5.0)  # 1..10
    source = Column(String, nullable=True)
    # "interaction:like:event:42", "dialog:session:7", "bio_extract", "compaction"
    embedding = Column(Text, nullable=True)  # JSON-вектор для семантического recall
    access_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_accessed_at = Column(DateTime, nullable=True)

    user = relationship("User")
