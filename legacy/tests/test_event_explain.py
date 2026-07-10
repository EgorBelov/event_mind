"""Тесты на человеческое описание события (кнопка «📖 Подробнее»)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.event_explain_service import (
    _fallback_summary,
    explain_event,
    invalidate,
)
from app.core.utils import utcnow_naive
from app.db.base import Base
from app.db.models.event import Event


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate()
    yield
    invalidate()


def _make_event(session, **overrides) -> Event:
    defaults = dict(
        title="DevOps Meetup", description="Митап про Kubernetes и observability.",
        format="offline", city="moscow", level="middle", date="2026-06-15",
        start_at=utcnow_naive() + timedelta(days=10),
        event_type="meetup", tech_stack='["Kubernetes", "Prometheus"]',
    )
    defaults.update(overrides)
    ev = Event(**defaults)
    session.add(ev)
    session.commit()
    return ev


def test_explain_uses_llm_when_available(db):
    ev = _make_event(db)
    with patch(
        "app.api.services.event_explain_service._build_summary_via_llm",
        return_value="Это митап про Kubernetes и observability в Москве для опытных инженеров.",
    ) as m:
        out = explain_event(db, ev.id)
    assert m.called
    assert "Kubernetes" in out["summary"]
    assert out["cached"] is False


def test_explain_falls_back_to_template_on_llm_failure(db):
    ev = _make_event(db)
    with patch(
        "app.api.services.event_explain_service._build_summary_via_llm",
        return_value=None,
    ):
        out = explain_event(db, ev.id)
    # fallback пишет из полей события — должен быть заголовок и описание.
    assert "DevOps Meetup" in out["summary"]
    assert "Kubernetes" in out["summary"]


def test_explain_caches_result(db):
    ev = _make_event(db)
    with patch(
        "app.api.services.event_explain_service._build_summary_via_llm",
        return_value="Первый ответ LLM.",
    ) as m:
        first = explain_event(db, ev.id)
        second = explain_event(db, ev.id)
    assert m.call_count == 1, "повторный запрос должен брать из кэша"
    assert first["summary"] == second["summary"]
    assert first["cached"] is False
    assert second["cached"] is True


def test_explain_404_when_event_missing(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        explain_event(db, 99999)
    assert exc.value.status_code == 404


def test_fallback_omits_unknown_fields(db):
    """unknown/any не должны попадать в шаблон как `unknown`."""
    ev = _make_event(
        db, format="unknown", city="any", level="unknown",
        event_type=None, tech_stack=None, description="",
    )
    text = _fallback_summary(ev)
    assert "unknown" not in text.lower()
    assert "any" not in text.lower().split()


def test_invalidate_clears_specific_event(db):
    """invalidate(event_id) сбрасывает кэш для одного события, не для всех."""
    ev1 = _make_event(db, title="Event A")
    ev2 = _make_event(db, title="Event B")
    with patch(
        "app.api.services.event_explain_service._build_summary_via_llm",
        side_effect=["A1", "B1", "A2"],
    ) as m:
        explain_event(db, ev1.id)
        explain_event(db, ev2.id)
        invalidate(ev1.id)
        explain_event(db, ev1.id)  # пересчёт
        explain_event(db, ev2.id)  # из кэша
    assert m.call_count == 3
