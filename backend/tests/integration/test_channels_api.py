"""Integration: привязка Telegram deep-link токеном + внутренний API-key."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")


def _register(client: TestClient, email: str) -> None:
    resp = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 201


def test_telegram_link_and_confirm_flow(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "tg@example.com")

        # авторизованный пользователь получает одноразовый токен + deep-link
        link = client.post("/api/v1/channels/telegram/link-token")
        assert link.status_code == 200
        token = link.json()["token"]
        assert link.json()["deep_link"]

        # бот подтверждает привязку по внутреннему API-key
        confirm = client.post(
            "/api/v1/channels/telegram/confirm",
            json={"token": token, "chat_id": "123456789"},
            headers={"X-API-Key": settings.api_shared_secret},
        )
        assert confirm.status_code == 200


def test_link_token_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/v1/channels/telegram/link-token")
        assert resp.status_code == 401


def test_confirm_rejects_wrong_api_key(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "tg2@example.com")
        token = client.post("/api/v1/channels/telegram/link-token").json()["token"]
        resp = client.post(
            "/api/v1/channels/telegram/confirm",
            json={"token": token, "chat_id": "111"},
            headers={"X-API-Key": "wrong-secret"},
        )
        assert resp.status_code == 403
