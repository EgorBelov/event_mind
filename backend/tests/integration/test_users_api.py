"""Integration: профиль и настройки уведомлений через /api/v1/users (M6.2).

Регистрируемся, логинимся (cookie), затем читаем/меняем профиль и prefs.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")


def _register(client: TestClient, email: str = "profile@example.com") -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text


def test_get_and_update_profile(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client)

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["city"] is None

        upd = client.patch(
            "/api/v1/users/me",
            json={"city": "Piter", "preferred_format": "online"},
        )
        assert upd.status_code == 200, upd.text
        body = upd.json()
        assert body["city"] == "spb"  # канонизация piter→spb
        assert body["preferred_format"] == "online"

        # изменение персистентно
        assert client.get("/api/v1/users/me").json()["city"] == "spb"


def test_get_and_update_preferences(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, email="prefs@example.com")

        prefs = client.get("/api/v1/users/me/preferences")
        assert prefs.status_code == 200
        assert prefs.json()["digest_frequency"] == "daily"

        upd = client.patch(
            "/api/v1/users/me/preferences",
            json={
                "digest_frequency": "weekly",
                "email_enabled": False,
                "quiet_hours_start": 23,
                "quiet_hours_end": 7,
            },
        )
        assert upd.status_code == 200, upd.text
        body = upd.json()
        assert body["digest_frequency"] == "weekly"
        assert body["email_enabled"] is False
        assert body["quiet_hours_start"] == 23

        # частичное обновление не сбрасывает остальное
        again = client.patch(
            "/api/v1/users/me/preferences", json={"telegram_enabled": True}
        )
        assert again.json()["digest_frequency"] == "weekly"
        assert again.json()["telegram_enabled"] is True


def test_profile_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/users/me").status_code == 401
        assert client.patch("/api/v1/users/me", json={"city": "x"}).status_code == 401
