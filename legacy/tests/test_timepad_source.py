"""Тесты Timepad-source: парсинг JSON-ответа в наш контракт ingestion.

Сам HTTP-вызов не делаем (нужен живой токен) — мокаем `httpx.get` и
проверяем, что `fetch_timepad_events` корректно собирает
{title, raw_description, source_url} и аккуратно обрабатывает ошибки.
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_response():
    """Минимальный валидный ответ Timepad с двумя событиями."""
    return {
        "values": [
            {
                "id": 12345,
                "name": "Python Meetup",
                "starts_at": "2026-06-15T19:00:00+0300",
                "ends_at": "2026-06-15T22:00:00+0300",
                "url": "https://python.timepad.ru/event/12345/",
                "description_short": "Короткое описание",
                "description_html": "<p>Подробное описание</p>",
                "location": {
                    "city": "Москва",
                    "address": "ул. Тверская, 1",
                    "country": "Россия",
                },
                "categories": [{"id": 452, "name": "IT и интернет"}],
            },
            {
                "id": 67890,
                "name": "DevOps Conf",
                "starts_at": "2026-07-01T10:00:00+0300",
                "url": "https://devops.timepad.ru/event/67890/",
                "description_short": "",
                "description_html": "",
                "location": {"city": "Санкт-Петербург"},
                "categories": [{"id": 452, "name": "IT и интернет"}],
            },
        ],
        "total": 2,
    }


def _mock_httpx(status: int, payload: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload or {}
    return m


def test_returns_empty_when_no_token():
    """Без TIMEPAD_TOKEN source молча возвращает [] (как luma/meetup)."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s:
        s.timepad_token = ""
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    assert out == []


def test_parses_valid_response(fake_response):
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(200, fake_response)) as get:
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)

    assert get.called
    headers = get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer tok"
    params = get.call_args.kwargs["params"]
    assert params["category_ids"] == "452"
    assert "starts_at_min" in params

    assert len(out) == 2
    first = out[0]
    assert first["title"] == "Python Meetup"
    assert first["source_url"] == "https://python.timepad.ru/event/12345/"
    # Структурные поля попадают в raw_description, чтобы LLM их распарсил
    assert "Москва" in first["raw_description"]
    assert "2026-06-15" in first["raw_description"]
    assert "ул. Тверская, 1" in first["raw_description"]
    assert "IT и интернет" in first["raw_description"]


def test_skips_items_without_title(fake_response):
    """Без `name` событие отбрасывается (LLM нечего нормализовать)."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    fake_response["values"][0]["name"] = ""
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(200, fake_response)):
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    titles = {e["title"] for e in out}
    assert "Python Meetup" not in titles
    assert "DevOps Conf" in titles


def test_uses_short_description_when_html_empty(fake_response):
    """Если description_html пуст — берём description_short."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(200, fake_response)):
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    assert "Подробное описание" in out[0]["raw_description"]


def test_handles_401_gracefully():
    """Неверный токен → пустой список, источник просто пропускается."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(401)):
        s.timepad_token = "wrong"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    assert out == []


def test_handles_429_rate_limit():
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(429)):
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    assert out == []


def test_handles_network_error():
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               side_effect=ConnectionError("DNS fail")):
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        out = fetch_timepad_events(limit=10)
    assert out == []


def test_cities_filter_passed_to_api():
    """Если TIMEPAD_CITIES задан — улетает в params."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(200, {"values": []})) as get:
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = "Москва,Санкт-Петербург"
        fetch_timepad_events(limit=5)
    params = get.call_args.kwargs["params"]
    assert params["cities"] == "Москва,Санкт-Петербург"


def test_limit_capped_at_100():
    """Timepad API max page = 100. Просим больше — clamp."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    with patch("app.ingestion.sources.timepad.settings") as s, \
         patch("app.ingestion.sources.timepad.httpx.get",
               return_value=_mock_httpx(200, {"values": []})) as get:
        s.timepad_token = "tok"
        s.timepad_category_ids = "452"
        s.timepad_cities = ""
        fetch_timepad_events(limit=500)
    assert get.call_args.kwargs["params"]["limit"] == 100
