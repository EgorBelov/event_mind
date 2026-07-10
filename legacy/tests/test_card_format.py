"""Регресс на отрисовку карточек: произвольный текст события не должен
ломать parse_mode Telegram (раньше Markdown падал на `*`/`_`/`[` и карточка
пропадала, помогало только листание)."""
from app.bot.handlers.recommendations import format_event_card
from app.bot.utils import esc as _esc


def _event():
    return {
        "title": "AI & ML <hack> *боль*",
        "topics": ["ai_ml"],
        "format": "online",
        "city": "any",
        "level": "beginner",
        "date": "2026-06-01",
        "description": "Скидка 100% на _курс_ [тут](x) `code`",
        "explanation": "Почему: тема AI & др.",
        "score": 9.1,
    }


def test_esc_handles_none_and_html():
    assert _esc(None) == ""
    assert _esc("a<b>&c") == "a&lt;b&gt;&amp;c"


def test_event_card_escapes_html_specials():
    text = format_event_card(_event())
    # опасные для HTML символы экранированы
    assert "&lt;hack&gt;" in text
    assert "AI &amp; ML" in text
    assert "<hack>" not in text
    # наш единственный разметочный тег — <b>…</b> вокруг заголовка
    assert text.startswith("<b>AI &amp; ML &lt;hack&gt; *боль*</b>")
    # markdown-спецсимволы больше не интерпретируются — остаются как есть
    assert "_курс_" in text and "*боль*" in text


def test_event_card_no_longer_includes_explanation():
    """После п.3 (выноса объяснения в кнопку «Почему?») карточка не содержит
    LLM-explanation — он отдаётся отдельным сообщением по запросу."""
    text = format_event_card(_event())
    assert "Почему:" not in text
    assert "Score:" not in text
