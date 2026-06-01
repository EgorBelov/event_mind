"""Тест hard-cap на user_memories."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user_memory import UserMemory
from app.recommender import memory as memory_mod


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_hard_cap_prunes_lowest_salience(db, monkeypatch):
    # Уменьшим cap для скорости теста.
    monkeypatch.setattr(memory_mod, "USER_MEMORY_HARD_CAP", 5)
    # Эмбеддингов не нужно — отрубаем тяжелую модель.
    monkeypatch.setattr("app.recommender.embeddings.embed_text", lambda t: [0.1])

    # Кладём 10 заметок с возрастающей salience.
    for i in range(10):
        memory_mod.write_memory(
            db, user_id=42, text=f"note {i}", salience=float(i + 1)
        )

    # После cap'а должно остаться 5 — с самыми высокими salience.
    rows = db.query(UserMemory).filter_by(user_id=42).all()
    saliences = sorted([r.salience for r in rows])
    assert len(rows) == 5
    # 5 самых высоких = [6, 7, 8, 9, 10]
    assert saliences == [6.0, 7.0, 8.0, 9.0, 10.0]
