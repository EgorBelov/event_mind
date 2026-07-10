"""Integration: bot-facing внутренний API (/api/v1/bot/*) с резолвом chat_id.

Флоу: регистрация → link-token (JWT) → confirm (internal key) → бот видит
статус/ленту по chat_id. Проверяем и защиту API-key, и 409 без привязки.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")

CHAT_ID = "987654321"


def _link_account(client: TestClient, settings: Settings, email: str) -> None:
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": "password123"}
        ).status_code
        == 201
    )
    token = client.post("/api/v1/channels/telegram/link-token").json()["token"]
    confirm = client.post(
        "/api/v1/channels/telegram/confirm",
        json={"token": token, "chat_id": CHAT_ID},
        headers={"X-API-Key": settings.api_shared_secret},
    )
    assert confirm.status_code == 200


def _key(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.api_shared_secret}


def test_bot_status_and_recommendations(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _link_account(client, settings, "botuser@example.com")

        status = client.get(
            "/api/v1/bot/status", params={"chat_id": CHAT_ID}, headers=_key(settings)
        )
        assert status.status_code == 200
        assert status.json()["linked"] is True

        recs = client.get(
            "/api/v1/bot/recommendations",
            params={"chat_id": CHAT_ID},
            headers=_key(settings),
        )
        assert recs.status_code == 200
        assert isinstance(recs.json(), list)  # пусто без событий — это ок


def test_bot_status_unlinked(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        status = client.get(
            "/api/v1/bot/status", params={"chat_id": "000"}, headers=_key(settings)
        )
        assert status.status_code == 200
        assert status.json()["linked"] is False


def test_bot_recommendations_unlinked_409(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        resp = client.get(
            "/api/v1/bot/recommendations",
            params={"chat_id": "000"},
            headers=_key(settings),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "not_linked"


def test_bot_requires_internal_api_key(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/v1/bot/status", params={"chat_id": CHAT_ID})
        assert resp.status_code == 403
