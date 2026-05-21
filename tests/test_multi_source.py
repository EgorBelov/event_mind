"""Tests for new ingestion sources (offline mocks)."""
import pytest


def test_kudago_parses_results(monkeypatch):
    from app.ingestion.sources import kudago

    class FakeResp:
        status_code = 200
        def json(self):
            return {"results": [
                {
                    "title": "AI Meetup",
                    "description": "Доклады по LLM",
                    "site_url": "https://example.com/ev1",
                    "place": {"city": {"name": "Москва"}},
                },
                {
                    "title": "Concert",
                    "description": "Не IT",
                    "site_url": "https://example.com/ev2",
                    "place": None,
                },
            ]}

    monkeypatch.setattr(kudago.httpx, "get", lambda *a, **kw: FakeResp())
    items = kudago.fetch_kudago_events(limit=10)
    assert len(items) == 2
    assert items[0]["title"] == "AI Meetup"
    assert "raw_description" in items[0]


def test_kudago_handles_http_error(monkeypatch):
    from app.ingestion.sources import kudago

    class FakeResp:
        status_code = 500
        def json(self): return {}

    monkeypatch.setattr(kudago.httpx, "get", lambda *a, **kw: FakeResp())
    assert kudago.fetch_kudago_events() == []


def test_luma_returns_empty_without_config(monkeypatch):
    from app.ingestion.sources import luma
    from app.core.config import settings
    monkeypatch.setattr(settings, "luma_calendars", "")
    assert luma.fetch_luma_events() == []


def test_luma_parses_ics(monkeypatch):
    from app.ingestion.sources import luma
    from app.core.config import settings

    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:AI Sync
DESCRIPTION:About LLMs
URL:https://lu.ma/ai-sync
LOCATION:Online
DTSTART:20260601T180000Z
END:VEVENT
END:VCALENDAR"""

    class FakeResp:
        status_code = 200
        text = ics

    monkeypatch.setattr(settings, "luma_calendars", "https://example.com/feed.ics")
    monkeypatch.setattr(luma.httpx, "get", lambda *a, **kw: FakeResp())
    items = luma.fetch_luma_events()
    assert len(items) == 1
    assert items[0]["title"] == "AI Sync"
    assert "Online" in items[0]["raw_description"]


def test_meetup_skipped_without_creds(monkeypatch):
    from app.ingestion.sources import meetup
    from app.core.config import settings
    monkeypatch.setattr(settings, "meetup_token", "")
    assert meetup.fetch_meetup_events() == []


def test_tg_skipped_without_channels(monkeypatch):
    from app.ingestion.sources import tg_channels
    from app.core.config import settings
    monkeypatch.setattr(settings, "tg_ingest_channels", "")
    assert tg_channels.fetch_telegram_events() == []


def test_tg_parses_web_preview_html(monkeypatch):
    """Парсер должен извлекать сообщения из t.me/s/{channel} HTML."""
    from app.ingestion.sources import tg_channels
    from app.core.config import settings

    html = """
    <html><body>
    <div class="tgme_widget_message" data-post="iteventsru/2293">
      <div class="tgme_widget_message_text" dir="auto">
        🚀 Митап для IT-проджектов от ЮMoney<br>
        21 мая в 18:00. Communication, AI tools, командное доверие.
      </div>
      <a class="tgme_widget_message_date" href="https://t.me/iteventsru/2293">
        <time datetime="2026-05-15T15:30:00+00:00">May 15</time>
      </a>
    </div>
    <div class="tgme_widget_message" data-post="iteventsru/2290">
      <div class="tgme_widget_message_text" dir="auto">
        Webinar Cloud.ru — стабильность PostgreSQL под нагрузкой
      </div>
      <a class="tgme_widget_message_date" href="https://t.me/iteventsru/2290">
        <time datetime="2026-04-28T12:00:00+00:00">Apr 28</time>
      </a>
    </div>
    <div class="tgme_widget_message" data-post="iteventsru/9999">
      <div class="tgme_widget_message_text" dir="auto">!!!</div>
    </div>
    </body></html>
    """

    class FakeResp:
        status_code = 200
        text = html

    monkeypatch.setattr(settings, "tg_ingest_channels", "iteventsru")
    monkeypatch.setattr(tg_channels.httpx, "get", lambda *a, **kw: FakeResp())

    items = tg_channels.fetch_telegram_events(limit_per_channel=10)
    assert len(items) == 2  # короткое "!!!" отфильтровано (< MIN_TEXT_LEN)
    assert items[0]["title"].startswith("🚀 Митап")
    assert items[0]["source_url"] == "https://t.me/iteventsru/2293"
    assert "Telegram-канал @iteventsru" in items[0]["raw_description"]


def test_tg_handles_http_error(monkeypatch):
    from app.ingestion.sources import tg_channels
    from app.core.config import settings

    class FakeResp:
        status_code = 404
        text = ""

    monkeypatch.setattr(settings, "tg_ingest_channels", "nonexistent")
    monkeypatch.setattr(tg_channels.httpx, "get", lambda *a, **kw: FakeResp())

    assert tg_channels.fetch_telegram_events() == []


def test_tg_silent_when_preview_disabled(monkeypatch):
    """Канал, у которого web-preview отключён, отдаёт страницу без .tgme_widget_message."""
    from app.ingestion.sources import tg_channels
    from app.core.config import settings

    class FakeResp:
        status_code = 200
        text = "<html><body><div>no messages here</div></body></html>"

    monkeypatch.setattr(settings, "tg_ingest_channels", "private_channel")
    monkeypatch.setattr(tg_channels.httpx, "get", lambda *a, **kw: FakeResp())

    assert tg_channels.fetch_telegram_events() == []


def test_tg_multi_channel(monkeypatch):
    """Несколько каналов через запятую — все обходятся."""
    from app.ingestion.sources import tg_channels
    from app.core.config import settings

    call_log: list[str] = []

    def fake_get(url, *a, **kw):
        call_log.append(url)
        class R:
            status_code = 200
            text = (
                '<div class="tgme_widget_message" data-post="X/1">'
                '<div class="tgme_widget_message_text">'
                'Полноценный анонс митапа на этой неделе с подробностями про время.'
                '</div></div>'
            )
        return R()

    monkeypatch.setattr(settings, "tg_ingest_channels", "iteventsru, ITMeeting")
    monkeypatch.setattr(tg_channels.httpx, "get", fake_get)

    items = tg_channels.fetch_telegram_events()
    assert len(call_log) == 2
    assert "iteventsru" in call_log[0]
    assert "ITMeeting" in call_log[1]
    assert len(items) == 2
