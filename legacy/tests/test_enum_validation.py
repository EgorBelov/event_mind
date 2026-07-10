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


# ── Фильтр «событие vs не-событие» ─────────────────────────────────────────


def test_drops_non_event_partnership_announcement():
    """Корпоративный анонс поиска партнёров → topics=[] (не мероприятие).

    Реальный кейс из Habr: «Компания приглашает ИТ-компании к сотрудничеству
    в партнерской сети». Тема выглядит IT, но это B2B-объявление: ни даты,
    ни площадки, ни формата, ни типа события."""
    raw = {
        "title": "Компания приглашает ИТ-компании к сотрудничеству в партнерской сети",
        "description": "Компания заказной разработки ищет ИТ-партнёров в Узбекистане...",
        "topics": ["backend", "business_analytics"],
        "format": "unknown", "city": "unknown", "level": "unknown",
        "seniority": "any", "event_type": "unknown",
        "date": "", "tech_stack": [], "quality_score": 6, "hype_score": 7,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == [], "должно отброситься как не-событие"


def test_drops_non_event_job_posting():
    """Вакансия без признаков мероприятия → topics=[]."""
    raw = {
        "title": "Открыта позиция Senior Python-разработчика в финтех",
        "description": "Ищем сеньора с опытом FastAPI и PostgreSQL...",
        "topics": ["backend"],
        "format": "unknown", "city": "unknown", "level": "unknown",
        "seniority": "senior", "event_type": "unknown",
        "date": "", "tech_stack": ["Python"], "quality_score": 5, "hype_score": 5,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == []


def test_keeps_event_with_only_date():
    """У реального события дата есть → не отбрасываем, даже если city/format
    пустые. Один сигнал из четырёх — уже достаточно, чтобы считать
    мероприятием."""
    raw = {
        "title": "DevOps Russia Meetup",
        "description": "Митап про Kubernetes",
        "topics": ["devops"],
        "format": "unknown", "city": "unknown", "level": "unknown",
        "seniority": "any", "event_type": "unknown",
        "date": "2026-07-15", "tech_stack": [], "quality_score": 7, "hype_score": 8,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == ["devops"]


def test_keeps_event_with_only_format():
    """Только формат указан — но всё равно похоже на мероприятие."""
    raw = {
        "title": "AI Webinar", "description": "Вебинар", "topics": ["ai_ml"],
        "format": "online", "city": "unknown", "level": "unknown",
        "seniority": "any", "event_type": "unknown",
        "date": "", "tech_stack": [], "quality_score": 6, "hype_score": 6,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == ["ai_ml"]


def test_keeps_event_with_only_event_type():
    """Распознан event_type — значит, модель уверена, что это мероприятие."""
    raw = {
        "title": "Backend Conf", "description": "Конференция",
        "topics": ["backend"],
        "format": "unknown", "city": "unknown", "level": "unknown",
        "seniority": "any", "event_type": "conference",
        "date": "", "tech_stack": [], "quality_score": 7, "hype_score": 7,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == ["backend"]


def test_keeps_event_with_only_city():
    """Указан конкретный город — значит, у мероприятия есть площадка."""
    raw = {
        "title": "Frontend Meetup", "description": "Митап",
        "topics": ["frontend"],
        "format": "unknown", "city": "moscow", "level": "unknown",
        "seniority": "any", "event_type": "unknown",
        "date": "", "tech_stack": [], "quality_score": 6, "hype_score": 6,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == ["frontend"]


def test_non_event_filter_does_not_run_on_already_empty_topics():
    """Если LLM уже вернула topics=[] (фильтр сработал на стороне модели),
    наш постпроцесс не должен что-то ломать дополнительно."""
    raw = {
        "title": "Не IT-событие", "description": "x", "topics": [],
        "format": "unknown", "city": "unknown", "level": "unknown",
        "seniority": "any", "event_type": "unknown",
        "date": "", "tech_stack": [], "quality_score": 1, "hype_score": 1,
    }
    out = _postprocess_normalized(raw)
    assert out["topics"] == []
