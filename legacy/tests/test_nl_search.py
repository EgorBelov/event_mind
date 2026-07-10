"""Тесты NL-поиска: LLM-extract фильтров и применение к SQL."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.nl_search_service import (
    _has_useful_filters,
    _postprocess,
    extract_filters,
    nl_search,
)
from app.core.utils import utcnow_naive
from app.db.base import Base
from app.db.models.event import Event


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    """LRU-кэш extract_filters_cached не должен протекать между тестами."""
    from app.api.services.nl_search_service import _extract_filters_cached
    _extract_filters_cached.cache_clear()


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


def _make_event(session, **overrides) -> Event:
    defaults = dict(
        title="DevOps митап", description="Митап про Kubernetes.",
        format="offline", city="moscow", level="middle", date="2026-06-15",
        start_at=utcnow_naive() + timedelta(days=10),
        event_type="meetup",
    )
    defaults.update(overrides)
    ev = Event(**defaults)
    session.add(ev)
    session.commit()
    return ev


# ── _postprocess: канонизация и валидация LLM-вывода ───────────────────────


def test_postprocess_canonicalizes_city_alias():
    """LLM эмитнула 'msk' → канонизируется в 'moscow'."""
    out = _postprocess({"city": "msk"})
    assert out["city"] == "moscow"


def test_postprocess_rejects_invalid_event_type():
    """Тип события не из домена → None."""
    out = _postprocess({"event_type": "rave_party"})
    assert out["event_type"] is None


def test_postprocess_filters_unknown_topics():
    """Тема не из seed-словаря отбрасывается."""
    out = _postprocess({"topics": ["ai_ml", "квантовая_магия", "devops"]})
    assert out["topics"] == ["ai_ml", "devops"]


def test_postprocess_swaps_inverted_date_range():
    """Если LLM выдала date_from > date_to — меняем местами, а не падаем."""
    out = _postprocess({"date_from": "2026-06-10", "date_to": "2026-06-03"})
    assert out["date_from"] == "2026-06-03"
    assert out["date_to"] == "2026-06-10"


def test_postprocess_rejects_invalid_iso():
    out = _postprocess({"date_from": "вчера"})
    assert out["date_from"] is None


def test_postprocess_empty_input_returns_blanks():
    out = _postprocess({})
    assert out["date_from"] is None
    assert out["city"] is None
    assert out["topics"] == []
    assert out["free_text"] == ""
    assert out["format"] is None


def test_postprocess_accepts_valid_format():
    assert _postprocess({"format": "online"})["format"] == "online"
    assert _postprocess({"format": "offline"})["format"] == "offline"
    assert _postprocess({"format": "hybrid"})["format"] == "hybrid"


def test_postprocess_rejects_invalid_or_meaningless_format():
    """'any' и 'unknown' валидны в БД, но как фильтр бесполезны → None."""
    assert _postprocess({"format": "any"})["format"] is None
    assert _postprocess({"format": "unknown"})["format"] is None
    assert _postprocess({"format": "zoom"})["format"] is None
    assert _postprocess({"format": ""})["format"] is None


# ── _has_useful_filters: «есть ли что-то структурированное» ────────────────


def test_has_useful_filters_detects_city():
    assert _has_useful_filters({"city": "moscow", "date_from": None, "topics": []})


def test_has_useful_filters_detects_format():
    """format — структурированный фильтр, должен учитываться (был баг: онлайн уходил в free_text)."""
    assert _has_useful_filters({"format": "online", "city": None, "topics": []})


def test_has_useful_filters_ignores_free_text_only():
    """Только free_text — не считается «структурированным» (это обычный поиск)."""
    assert not _has_useful_filters({"free_text": "python", "city": None, "topics": []})


# ── extract_filters: интеграция с LRU-кэшем ────────────────────────────────


def test_extract_filters_uses_cache():
    """Одинаковый запрос — один LLM-вызов."""
    mock_result = {
        "date_from": "2026-06-03", "date_to": "2026-06-10",
        "city": "moscow", "event_type": "conference",
        "topics": ["ai_ml"], "free_text": "",
    }
    with patch(
        "app.api.services.nl_search_service._extract_filters_raw",
        return_value=mock_result,
    ) as m:
        extract_filters("конференции с 3 по 10 июня в Москве")
        extract_filters("конференции с 3 по 10 июня в Москве")
        # Нормализация: разный регистр / пробелы — один кэш-ключ.
        extract_filters("Конференции  с 3 по 10 июня в Москве")
    assert m.call_count == 1


def test_extract_filters_empty_query_short_circuits():
    """Пустой запрос не дёргает LLM."""
    with patch(
        "app.api.services.nl_search_service._extract_filters_raw",
    ) as m:
        out = extract_filters("")
    assert m.call_count == 0
    assert out["free_text"] == ""


# ── nl_search: применение фильтров к SQL ───────────────────────────────────


def test_nl_search_filters_by_city(db):
    _make_event(db, title="Москва митап", city="moscow")
    _make_event(db, title="Питер митап", city="spb")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": "moscow",
            "event_type": None, "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "митапы в Москве")
    titles = {e["title"] for e in result["events"]}
    assert "Москва митап" in titles
    assert "Питер митап" not in titles
    assert result["extracted"] is True
    assert result["filters"]["city"] == "moscow"


def test_nl_search_filters_by_date_range(db):
    now = utcnow_naive()
    _make_event(db, title="Через 5 дней", start_at=now + timedelta(days=5))
    _make_event(db, title="Через 20 дней", start_at=now + timedelta(days=20))
    df = (now + timedelta(days=3)).date().isoformat()
    dt = (now + timedelta(days=10)).date().isoformat()
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": df, "date_to": dt, "city": None,
            "event_type": None, "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "митапы на следующей неделе")
    titles = {e["title"] for e in result["events"]}
    assert "Через 5 дней" in titles
    assert "Через 20 дней" not in titles


def test_nl_search_date_filter_excludes_events_without_date(db):
    """«любое событие в августе» не должен возвращать статьи без start_at.

    Раньше фильтр был NULL-сейф (Event.start_at IS NULL OR start_at >= ...),
    и хабровские новости без даты пролезали в выдачу под любой запрос
    с диапазоном — это вводило в заблуждение."""
    now = utcnow_naive()
    _make_event(db, title="Митап в августе", start_at=now + timedelta(days=60))
    _make_event(db, title="Статья без даты", start_at=None, date="")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": (now + timedelta(days=55)).date().isoformat(),
            "date_to": (now + timedelta(days=85)).date().isoformat(),
            "city": None, "event_type": None, "format": None,
            "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "любое событие в августе")
    titles = {e["title"] for e in result["events"]}
    assert "Митап в августе" in titles
    assert "Статья без даты" not in titles


def test_nl_search_filters_by_event_type(db):
    _make_event(db, title="Конф A", event_type="conference")
    _make_event(db, title="Митап B", event_type="meetup")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "conference", "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "конференции")
    titles = {e["title"] for e in result["events"]}
    assert "Конф A" in titles
    assert "Митап B" not in titles


def test_nl_search_falls_back_when_llm_empty(db):
    """LLM не извлекла фильтров и free_text пустой → combined_search."""
    _make_event(db, title="Python митап", description="про Django")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": None, "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "случайный текст")
    assert result["fallback_used"] is True
    assert result["extracted"] is False


def test_nl_search_excludes_past_events(db):
    """upcoming_only применяется в NL-поиске тоже."""
    now = utcnow_naive()
    _make_event(db, title="Прошлый митап", start_at=now - timedelta(days=30))
    _make_event(db, title="Будущий митап", start_at=now + timedelta(days=5))
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "meetup", "format": None, "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "митапы")
    titles = {e["title"] for e in result["events"]}
    assert "Будущий митап" in titles
    assert "Прошлый митап" not in titles


def test_nl_search_filters_by_format(db):
    """«онлайн конференции» — раньше «онлайн» уходило в free_text и убивало
    выдачу. Теперь должно идти как format=online."""
    _make_event(db, title="Онлайн конф", format="online", event_type="conference")
    _make_event(db, title="Оффлайн конф", format="offline", event_type="conference")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "conference", "format": "online",
            "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "онлайн конференции")
    titles = {e["title"] for e in result["events"]}
    assert "Онлайн конф" in titles
    assert "Оффлайн конф" not in titles
    assert result["relaxed"] is False


# ── Relax-fallback при 0 результатах ──────────────────────────────────────


def test_nl_search_relaxes_when_strict_returns_zero(db):
    """В БД нет онлайн-конференций. Строгий фильтр даёт 0 → релаксируем format,
    показываем оффлайн с пометкой."""
    _make_event(db, title="Оффлайн конф", format="offline", event_type="conference")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "conference", "format": "online",
            "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "онлайн конференции")
    titles = {e["title"] for e in result["events"]}
    assert "Оффлайн конф" in titles
    assert result["relaxed"] is True
    assert "формата" in result["dropped"]
    # original_filters сохраняет исходный запрос для отображения
    assert result["original_filters"]["format"] == "online"


def test_nl_search_relax_keeps_strongest_filter(db):
    """Релаксация снимает по одному в порядке _RELAX_ORDER. Если убрали
    free_text — и нашли событие, дату/город НЕ трогаем."""
    _make_event(db, title="Митап в москве", city="moscow", event_type="meetup")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": "moscow",
            "event_type": "meetup", "format": None,
            "topics": [], "free_text": "несуществующее_слово",
        },
    ):
        result = nl_search(db, "митапы в москве про несуществующее")
    assert len(result["events"]) == 1
    assert result["relaxed"] is True
    assert result["dropped"] == ["слов из текста"]
    # city и event_type остались
    assert result["filters"]["city"] == "moscow"
    assert result["filters"]["event_type"] == "meetup"


def test_nl_search_relax_returns_empty_when_nothing_matches(db):
    """Если ни один релакс-уровень не дал событий — relaxed=True + dropped
    показывает что пробовали, events=[]."""
    # Пустая БД
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": "moscow",
            "event_type": "conference", "format": "online",
            "topics": ["ai_ml"], "free_text": "django",
        },
    ):
        result = nl_search(db, "django ai_ml конференции онлайн в москве")
    assert result["events"] == []
    assert result["relaxed"] is True
    assert len(result["dropped"]) >= 1  # хотя бы что-то пробовали снять


def test_nl_search_relax_caps_to_single_event(db):
    """При релаксации возвращаем ОДНО ближайшее событие, даже если матчит много.
    «Лучше одно с честной пометкой, чем 8 случайных» — контракт после правки #55."""
    # 5 оффлайн-конференций — все подойдут после снятия format='online'
    for i in range(5):
        _make_event(db, title=f"Оффлайн конф {i}", format="offline", event_type="conference")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "conference", "format": "online",
            "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "онлайн конференции", limit=5)
    assert result["relaxed"] is True
    assert len(result["events"]) == 1, "relax-fallback должен показывать 1 событие, не пачку"


def test_nl_search_strict_respects_limit(db):
    """Строгий хит уважает limit (5 по умолчанию)."""
    for i in range(8):
        _make_event(db, title=f"Митап {i}", event_type="meetup")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": None, "date_to": None, "city": None,
            "event_type": "meetup", "format": None, "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "митапы")  # limit=5 default
    assert result["relaxed"] is False
    assert len(result["events"]) == 5


def test_nl_search_relax_skips_already_empty_filters(db):
    """Если topics уже пустой — релакс его не «снимает» дважды."""
    _make_event(db, title="Какой-то митап", event_type="meetup")
    with patch(
        "app.api.services.nl_search_service.extract_filters",
        return_value={
            "date_from": "2099-01-01", "date_to": "2099-12-31", "city": None,
            "event_type": "meetup", "format": None,
            "topics": [], "free_text": "",
        },
    ):
        result = nl_search(db, "митапы в 2099")
    # topics пустой и сразу пропускается, free_text пустой — пропускается.
    # Снимется только date.
    assert result["relaxed"] is True
    assert "темы" not in result["dropped"]
    assert "слов из текста" not in result["dropped"]
    assert "даты" in result["dropped"]


def test_nl_search_empty_query():
    """Пустой запрос → пустой ответ, без LLM."""
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    try:
        with patch(
            "app.api.services.nl_search_service.extract_filters",
        ) as m:
            result = nl_search(sess, "")
        assert m.call_count == 0
        assert result["events"] == []
    finally:
        sess.close()
