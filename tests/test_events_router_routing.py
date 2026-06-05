"""Регресс-тесты: порядок маршрутов в /events.

FastAPI берёт первый совпавший маршрут. Если объявить `GET /{event_id}`
до `GET /nl-search`, то запрос `/events/nl-search` спарсится как
`event_id="nl-search"` и упадёт 422 — даже до того, как nl-search роут
получит шанс. Эти тесты держат правильный порядок зафиксированным.
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.events import router as events_router
from app.db.dependencies import get_db


@pytest.fixture
def client():
    """Не трогаем реальную БД — get_db переопределён на no-op session.

    Тесты здесь проверяют исключительно роутинг (порядок маршрутов).
    Логика NL-поиска и get_event_by_id замокана отдельно.
    """
    class _NoopSession:
        def query(self, *a, **kw):
            class _Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return _Q()

    def _override_get_db():
        yield _NoopSession()

    app = FastAPI()
    app.include_router(events_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_nl_search_route_matches_before_event_id(client):
    """`/events/nl-search` НЕ должен интерпретироваться как event_id=nl-search.

    До фикса порядка маршрутов отвечало 422 «invalid event_id»."""
    expected = {
        "events": [], "filters": {}, "original_filters": {},
        "extracted": True, "fallback_used": False, "relaxed": False, "dropped": [],
    }
    with patch(
        "app.api.services.nl_search_service.nl_search",
        return_value=expected,
    ) as m:
        r = client.get("/events/nl-search", params={"q": "события в москве"})
    assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
    assert r.json() == expected
    assert m.called


def test_event_by_id_still_works_for_int(client):
    """`/events/{id}` с числовым id всё ещё попадает в get_event_by_id (404 от no-op БД)."""
    r = client.get("/events/9999")
    assert r.status_code == 404, f"Got {r.status_code}: {r.text}"


def test_event_by_id_rejects_non_int(client):
    """`/events/abc` — не существует ни как nl-search, ни как int → 422."""
    r = client.get("/events/abc")
    assert r.status_code == 422
