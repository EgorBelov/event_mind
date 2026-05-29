"""Tests for long-term memory agent (mem0-style)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User
from app.db.models.user_memory import UserMemory
from app.recommender.memory import (
    compact_user_memories,
    extract_from_dialog,
    extract_from_interaction,
    recall,
    write_memory,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _seed(db):
    t = Topic(code="ai_ml", title="AI")
    db.add(t)
    db.flush()
    user = User(
        telegram_id=42, username="u", preferred_format="online", city="any",
        topic_weights=json.dumps({"ai_ml": 3}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    ev = Event(
        title="LLM Workshop", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


# ─── write_memory ────────────────────────────────────────────────────────


def test_write_memory_persists_with_embedding(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.5, 0.5, 0.0])

    row = write_memory(db, user.id, "Хочет перейти в ML", category="goal", salience=8.0, source="test")
    db.commit()

    assert row is not None
    assert row.category == "goal"
    assert row.salience == 8.0
    assert json.loads(row.embedding) == [0.5, 0.5, 0.0]


def test_write_memory_clamps_salience(db):
    user, _ = _seed(db)
    row = write_memory(db, user.id, "x", salience=15.0)
    assert row.salience == 10.0
    row2 = write_memory(db, user.id, "y", salience=-5.0)
    assert row2.salience == 1.0


def test_write_memory_rejects_invalid_category(db):
    user, _ = _seed(db)
    row = write_memory(db, user.id, "x", category="DANGEROUS_CATEGORY")
    assert row.category == "other"


def test_write_memory_returns_none_on_empty_text(db):
    user, _ = _seed(db)
    assert write_memory(db, user.id, "") is None
    assert write_memory(db, user.id, "   ") is None


def test_write_memory_survives_embedding_failure(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: (_ for _ in ()).throw(RuntimeError("no model")))
    row = write_memory(db, user.id, "x", salience=5.0)
    assert row is not None
    assert row.embedding is None


# ─── recall ──────────────────────────────────────────────────────────────


def test_recall_ranks_by_cosine_similarity(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod

    # Заметки с разными «направлениями»
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    a = write_memory(db, user.id, "Любит AI", category="interest", salience=7.0)

    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.0, 1.0, 0.0])
    b = write_memory(db, user.id, "Любит DevOps", category="interest", salience=5.0)
    db.commit()

    # Query совпадает с направлением a
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    out = recall(db, user.id, "AI events please", k=2)
    assert len(out) == 2
    assert out[0]["id"] == a.id  # ближе по семантике
    assert out[1]["id"] == b.id


def test_recall_increments_access_count(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])

    row = write_memory(db, user.id, "x", salience=5.0)
    db.commit()
    assert row.access_count == 0

    recall(db, user.id, "x", k=1)
    db.refresh(row)
    assert row.access_count == 1
    assert row.last_accessed_at is not None

    recall(db, user.id, "x", k=1)
    db.refresh(row)
    assert row.access_count == 2


def test_recall_filters_by_min_salience(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])

    write_memory(db, user.id, "weak", salience=2.0)
    write_memory(db, user.id, "strong", salience=8.0)
    db.commit()

    out = recall(db, user.id, "x", k=10, min_salience=5.0)
    assert len(out) == 1
    assert out[0]["text"] == "strong"


def test_recall_falls_back_when_embedding_unavailable(db, monkeypatch):
    user, _ = _seed(db)
    # Записи без эмбеддингов — embed_text падает
    import app.recommender.embeddings as emb_mod

    def boom(text):
        raise RuntimeError("no model")

    monkeypatch.setattr(emb_mod, "embed_text", boom)

    write_memory(db, user.id, "fact A", salience=4.0)
    write_memory(db, user.id, "fact B", salience=9.0)
    db.commit()

    out = recall(db, user.id, "anything", k=5)
    assert len(out) == 2
    # При fallback порядок: salience DESC → B первым
    assert out[0]["text"] == "fact B"


def test_recall_empty_returns_empty(db):
    user, _ = _seed(db)
    assert recall(db, user.id, "x") == []


# ─── extract_from_interaction (с моком LLM) ──────────────────────────────


class FakeResp:
    def __init__(self, content): self.content = content


def _patch_llm(monkeypatch, content):
    class FakeLLM:
        def invoke(self, msgs): return FakeResp(content)

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())


def test_extract_from_interaction_writes_memory(db, monkeypatch):
    user, ev = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [
            {"text": "Активно интересуется LLM-практикой", "category": "interest", "salience": 7},
        ]
    }))
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.1, 0.2, 0.3])

    n = extract_from_interaction(db, user, ev, "like")
    db.commit()
    assert n == 1
    rows = db.query(UserMemory).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].source.startswith("interaction:like:event:")


def test_extract_from_interaction_filters_low_salience(db, monkeypatch):
    user, ev = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [
            {"text": "тривиальный факт", "category": "interest", "salience": 2},
        ]
    }))

    n = extract_from_interaction(db, user, ev, "like")
    assert n == 0


def test_extract_from_interaction_returns_zero_on_invalid_json(db, monkeypatch):
    user, ev = _seed(db)
    _patch_llm(monkeypatch, "not json at all")
    assert extract_from_interaction(db, user, ev, "like") == 0


def test_extract_from_interaction_skips_non_feedback_actions(db, monkeypatch):
    user, ev = _seed(db)
    # LLM не должен даже зваться, но на всякий случай зарядим валидный JSON
    _patch_llm(monkeypatch, json.dumps({"items": [{"text": "x", "category": "other", "salience": 9}]}))
    assert extract_from_interaction(db, user, ev, "view") == 0


# ─── extract_from_dialog ─────────────────────────────────────────────────


def test_extract_from_dialog_writes_multiple(db, monkeypatch):
    user, _ = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [
            {"text": "Хочет перейти в ML за 6 месяцев", "category": "goal", "salience": 8},
            {"text": "Предпочитает онлайн-формат", "category": "event_pref", "salience": 6},
        ]
    }))
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.0, 0.0, 1.0])

    history = [
        {"role": "user", "content": "Хочу стать ML инженером за полгода"},
        {"role": "assistant", "content": "Окей, вот план..."},
    ]
    n = extract_from_dialog(db, user, history, source="dialog:test")
    db.commit()
    assert n == 2
    cats = {r.category for r in db.query(UserMemory).filter_by(user_id=user.id).all()}
    assert "goal" in cats and "event_pref" in cats


def test_extract_from_dialog_skipped_on_empty_history(db, monkeypatch):
    user, _ = _seed(db)
    _patch_llm(monkeypatch, json.dumps({"items": [{"text": "x", "category": "other", "salience": 9}]}))
    assert extract_from_dialog(db, user, []) == 0


# ─── compact ─────────────────────────────────────────────────────────────


def test_compact_skipped_below_threshold(db):
    user, _ = _seed(db)
    write_memory(db, user.id, "x", salience=5.0)
    db.commit()
    r = compact_user_memories(db, user.id, threshold=10)
    assert r["status"] == "skipped"


def test_compact_summarizes_when_above_threshold(db, monkeypatch):
    user, _ = _seed(db)
    # 12 заметок в категории "interest"
    for i in range(12):
        write_memory(db, user.id, f"факт {i}", category="interest", salience=5.0)
    db.commit()

    _patch_llm(monkeypatch, json.dumps({
        "items": [
            {"text": "сжатый факт А", "category": "interest", "salience": 7},
            {"text": "сжатый факт Б", "category": "interest", "salience": 6},
        ]
    }))
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.0, 0.0, 1.0])

    r = compact_user_memories(db, user.id, threshold=10, target_per_category=3)
    db.commit()
    assert r["status"] == "ok"
    assert r["removed"] == 12
    assert r["added"] == 2

    rows = db.query(UserMemory).filter_by(user_id=user.id, category="interest").all()
    texts = {r.text for r in rows}
    assert texts == {"сжатый факт А", "сжатый факт Б"}
    assert all(r.source == "compaction" for r in rows)


# ─── Integration: copilot tool ───────────────────────────────────────────


def test_recall_tool_via_dispatch(db, monkeypatch):
    user, _ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])

    write_memory(db, user.id, "Хочет в ML", category="goal", salience=8.0)
    db.commit()

    from app.agents.copilot.tools import dispatch_tool
    result = dispatch_tool("recall_about_user", {"query": "цели", "k": 3}, db=db, telegram_id=42)
    assert result["count"] >= 1
    assert any("ML" in m["text"] for m in result["memories"])
