"""Unit: BotApiClient против httpx.MockTransport (без живого API).

Проверяем маппинг эндпоинтов, проброс X-API-Key и деградацию на ошибках.
"""
from __future__ import annotations

import httpx
import pytest

from eventmind.interfaces.bot.api_client import BotApiClient


class _Recorder:
    def __init__(self, responder: object) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)  # type: ignore[operator]


def _client_with(
    monkeypatch: pytest.MonkeyPatch, responder: object
) -> tuple[BotApiClient, _Recorder]:
    rec = _Recorder(responder)
    transport = httpx.MockTransport(rec.handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return BotApiClient("http://api:8000", "secret"), rec


async def test_confirm_link_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client, rec = _client_with(
        monkeypatch,
        lambda req: httpx.Response(200, json={"detail": "Telegram привязан к аккаунту 7"}),
    )
    ok, detail = await client.confirm_link("tok-1", "555")
    assert ok is True
    assert "привязан" in detail
    req = rec.requests[0]
    assert req.headers["X-API-Key"] == "secret"
    assert req.url.path == "/api/v1/channels/telegram/confirm"


async def test_confirm_link_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_with(
        monkeypatch,
        lambda req: httpx.Response(
            400, json={"error": {"code": "token_invalid", "message": "Токен истёк"}}
        ),
    )
    ok, detail = await client.confirm_link("bad", "555")
    assert ok is False
    assert detail == "Токен истёк"


async def test_status_linked(monkeypatch: pytest.MonkeyPatch) -> None:
    client, rec = _client_with(
        monkeypatch, lambda req: httpx.Response(200, json={"linked": True, "user_id": 7})
    )
    assert await client.status("555") is True
    assert rec.requests[0].url.params["chat_id"] == "555"


async def test_recommendations_not_linked_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_with(
        monkeypatch,
        lambda req: httpx.Response(409, json={"error": {"code": "not_linked", "message": "x"}}),
    )
    assert await client.recommendations("555") == []


async def test_recommendations_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_with(
        monkeypatch,
        lambda req: httpx.Response(200, json=[{"event_id": 1, "title": "A"}]),
    )
    items = await client.recommendations("555")
    assert items[0]["event_id"] == 1


async def test_interact_posts_action(monkeypatch: pytest.MonkeyPatch) -> None:
    client, rec = _client_with(monkeypatch, lambda req: httpx.Response(200, json={"status": "ok"}))
    ok = await client.interact("555", 42, "like")
    assert ok is True
    body = rec.requests[0].read().decode()
    assert '"event_id": 42' in body or '"event_id":42' in body


async def test_nl_search_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_with(
        monkeypatch,
        lambda req: httpx.Response(200, json={"relaxed": True, "results": [{"id": 3}]}),
    )
    res = await client.nl_search("AI в июне")
    assert res["relaxed"] is True
    assert res["results"][0]["id"] == 3


async def test_event_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_with(monkeypatch, lambda req: httpx.Response(404, json={}))
    assert await client.event(999) is None


async def test_http_error_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client, _ = _client_with(monkeypatch, boom)
    assert await client.recommendations("555") == []
    assert await client.status("555") is False
