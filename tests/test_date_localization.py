"""Тесты локализованного рендера дат в боте."""
from app.bot.utils import format_event_date


def test_renders_iso_with_time_in_moscow():
    # 2026-06-01 19:00 UTC -> Moscow = +03 = 22:00
    card = {"start_at": "2026-06-01T19:00:00"}
    out = format_event_date(card)
    assert "1 июня 2026" in out
    assert "22:00" in out
    assert "Moscow" in out


def test_renders_iso_without_time():
    # date-only — time-часть не показываем
    card = {"start_at": "2026-12-15T00:00:00"}
    out = format_event_date(card)
    assert "декабря" in out
    # ровный полночь UTC → 03:00 MSK, поэтому время покажем
    assert "03:00" in out


def test_fallback_to_string_date_when_no_start_at():
    card = {"date": "лето 2026"}
    out = format_event_date(card)
    assert out == "лето 2026"


def test_fallback_to_em_dash_when_nothing():
    assert format_event_date({}) == "—"


def test_invalid_iso_falls_back_to_date_string():
    card = {"start_at": "not-an-iso", "date": "16-17 марта"}
    out = format_event_date(card)
    assert out == "16-17 марта"
