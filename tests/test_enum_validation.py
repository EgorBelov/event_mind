"""Тесты строгой enum-валидации полей нормализатора событий."""
import pytest

from app.agents.event_normalization.agent import (
    _ALLOWED_EVENT_TYPE,
    _ALLOWED_FORMAT,
    _ALLOWED_SENIORITY,
    _normalize_enum_field,
    _postprocess_normalized,
)


@pytest.mark.parametrize("val", ["online", "offline", "hybrid", "any", "unknown"])
def test_format_accepts_allowed(val):
    assert _normalize_enum_field(
        val, allowed=_ALLOWED_FORMAT, default="unknown", label="format",
    ) == val


def test_format_rejects_outside_domain():
    for bad in ["virtual_online_in_zoom", "ZOOM", "очно", "", None, 42]:
        assert _normalize_enum_field(
            bad, allowed=_ALLOWED_FORMAT, default="unknown", label="format",
        ) == "unknown"


def test_seniority_rejects_outside_domain():
    assert _normalize_enum_field(
        "principal", allowed=_ALLOWED_SENIORITY, default="any", label="seniority",
    ) == "any"
    assert _normalize_enum_field(
        "middle", allowed=_ALLOWED_SENIORITY, default="any", label="seniority",
    ) == "middle"


def test_event_type_rejects_outside_domain():
    assert _normalize_enum_field(
        "rave_party", allowed=_ALLOWED_EVENT_TYPE, default="unknown", label="event_type",
    ) == "unknown"


def test_open_domain_rejects_malformed():
    # open-domain (city/level): принимаем slug, но мусор схлопываем
    assert _normalize_enum_field(
        "novosibirsk", allowed=None, default="unknown", label="city",
    ) == "novosibirsk"
    assert _normalize_enum_field(
        "это длинная фраза с пробелами", allowed=None, default="unknown", label="city",
    ) == "unknown"
    # длиннее 32 символов
    assert _normalize_enum_field(
        "a" * 33, allowed=None, default="unknown", label="city",
    ) == "unknown"


def test_postprocess_normalizes_garbage_format():
    """Интеграция: словарь от LLM с мусорным format / seniority / event_type."""
    raw = {
        "title": "Test", "description": "x", "topics": ["ai_ml"],
        "format": "virtual_zoom_call", "city": "Moscow", "level": "Easy",
        "seniority": "principal", "event_type": "rave",
        "date": "2026-06-01", "tech_stack": [], "quality_score": 7, "hype_score": 8,
    }
    out = _postprocess_normalized(raw)
    assert out["format"] == "unknown"
    assert out["seniority"] == "any"
    assert out["event_type"] == "unknown"
    # city/level прошли slugify (open-domain), не сваливаются
    assert out["city"] == "moscow"
    assert out["level"] == "easy"
