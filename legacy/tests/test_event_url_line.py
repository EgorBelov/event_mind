"""Тесты хелпера `event_url_line`: ссылка на источник в карточках событий."""
from app.bot.utils import event_url_line


def test_returns_anchor_when_url_present():
    line = event_url_line({"source_url": "https://habr.com/post/42"})
    assert line.startswith("\n<a href=")
    assert 'href="https://habr.com/post/42"' in line
    assert "Открыть на источнике" in line


def test_returns_empty_when_no_url():
    assert event_url_line({}) == ""
    assert event_url_line({"source_url": None}) == ""
    assert event_url_line({"source_url": ""}) == ""
    assert event_url_line({"source_url": "   "}) == ""


def test_custom_label():
    line = event_url_line(
        {"source_url": "https://example.com"}, label="Открыть"
    )
    assert ">Открыть<" in line


def test_url_with_quotes_is_escaped():
    """href с кавычками без экранирования валит Telegram-парсер."""
    line = event_url_line({"source_url": 'https://x.com/?a="b"&c=1'})
    # двойная кавычка → &quot;, амперсанд → &amp;
    assert '"b"' not in line
    assert "&quot;" in line
    assert "&amp;" in line
