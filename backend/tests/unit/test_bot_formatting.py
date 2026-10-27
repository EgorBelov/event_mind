"""Unit: чистые форматтеры карточек бота (без aiogram/сети)."""
from __future__ import annotations

from eventmind.interfaces.bot.formatting import (
    event_url_line,
    format_event_date,
    render_agent_text,
    render_event_card,
    to_plain,
)
from eventmind.interfaces.bot.keyboards import agent_confirm_keyboard


def test_format_date_from_iso_without_time_shows_only_date() -> None:
    # 00:00 UTC — источник не дал время → без «03:00 MSK».
    assert format_event_date({"start_at": "2026-06-16T00:00:00+00:00"}) == "16 июня 2026"


def test_format_date_with_time_localizes_to_msk() -> None:
    out = format_event_date({"start_at": "2026-06-16T16:00:00+00:00"})
    assert out == "16 июня 2026, 19:00 Moscow"


def test_format_date_bare_iso_string_humanized() -> None:
    assert format_event_date({"date": "2026-06-16"}) == "16 июня 2026"


def test_format_date_freeform_kept_as_is() -> None:
    assert format_event_date({"date": "лето 2026"}) == "лето 2026"


def test_format_date_empty() -> None:
    assert format_event_date({}) == "—"


def test_event_url_line_escapes_and_wraps() -> None:
    line = event_url_line({"source_url": "https://ex.com/a?b=1&c=2"})
    assert line.startswith("\n<a href=")
    assert "&amp;" in line


def test_event_url_line_empty_when_no_url() -> None:
    assert event_url_line({"source_url": ""}) == ""


def test_render_card_has_title_and_topics() -> None:
    card = render_event_card(
        {
            "title": "PyCon <2026>",
            "date": "2026-06-16",
            "city": "moscow",
            "format": "offline",
            "topics": ["python", "ml"],
            "description": "Большая конференция",
            "source_url": "https://ex.com",
        },
        score=1.234,
    )
    assert "<b>PyCon &lt;2026&gt;</b>" in card  # экранирование
    assert "#python" in card
    assert "★ 1.23" in card
    assert '<a href="https://ex.com">' in card


def test_to_plain_strips_tags() -> None:
    assert to_plain("<b>Hi</b> &amp; bye") == "Hi & bye"


def test_render_agent_text_escapes_html() -> None:
    assert render_agent_text({"text": "Go <b>не</b> & ML"}) == "Go &lt;b&gt;не&lt;/b&gt; &amp; ML"
    assert render_agent_text({"text": "  "}) == "Готово."


def test_agent_confirm_keyboard_fits_callback_limit() -> None:
    action_id = "f" * 32  # uuid4().hex
    kb = agent_confirm_keyboard(action_id)
    yes, no = kb.inline_keyboard[0]
    assert yes.callback_data == f"agent:yes:{action_id}"
    assert no.callback_data == f"agent:no:{action_id}"
    assert all(len((b.callback_data or "").encode()) <= 64 for b in (yes, no))



def test_feedback_keyboard_has_similar_button() -> None:
    from eventmind.interfaces.bot.keyboards import feedback_keyboard

    rows = feedback_keyboard(7, "https://x").inline_keyboard
    data = [b.callback_data for row in rows for b in row]
    assert "sim:7" in data and "more:7" in data
    assert [len(r) for r in rows] == [3, 2, 1]
