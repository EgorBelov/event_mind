"""Unit: чистый парсинг источников (habr HTML, kudago JSON) без сети."""
from __future__ import annotations

from eventmind.infrastructure.sources.habr import parse_habr_html
from eventmind.infrastructure.sources.kudago import parse_kudago_items

_HABR_HTML = """
<html><body>
<section class="tm-block">
  <a class="tm-event-card__title-link" href="/ru/events/1/">Python MeetUp #14</a>
  <div class="tm-event-card__day">16 июня</div>
  <div class="tm-event-card__places-list">Москва</div>
  <div class="tm-event-card__categories">Backend</div>
</section>
<section class="tm-block">
  <a class="tm-event-card__title-link" href="https://habr.com/ru/events/2/">DevOps Day</a>
  <div class="tm-event-card__day">20 июня</div>
</section>
<section class="tm-block">
  <div>без заголовка — пропускается</div>
</section>
</body></html>
"""


def test_parse_habr_html() -> None:
    drafts = parse_habr_html(_HABR_HTML)
    assert len(drafts) == 2
    first = drafts[0]
    assert first.title == "Python MeetUp #14"
    assert first.source_url == "https://habr.com/ru/events/1/"  # относительный → абсолютный
    assert "Москва" in first.raw_description
    # второй — абсолютный URL остаётся как есть
    assert drafts[1].source_url == "https://habr.com/ru/events/2/"


def test_parse_habr_limit() -> None:
    assert len(parse_habr_html(_HABR_HTML, limit=1)) == 1


def test_parse_kudago_items() -> None:
    items = [
        {
            "title": "AI Workshop",
            "description": "про ML",
            "site_url": "http://k/1",
            "place": {"city": {"name": "Казань"}},
        },
        {"short_title": "No title fallback", "description": "x", "site_url": "http://k/2"},
        {"description": "пропускается без title"},
    ]
    drafts = parse_kudago_items(items)
    assert len(drafts) == 2
    assert drafts[0].title == "AI Workshop"
    assert "Казань" in drafts[0].raw_description
    assert drafts[1].title == "No title fallback"
