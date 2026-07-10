"""Integration: auth-flow через /api/v1 против живых Postgres+Redis.

Проверяет полный путь регистрация→письмо(outbox)→верификация→логин→protected,
сброс пароля и транзакционность outbox.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from eventmind.config import Settings
from eventmind.infrastructure.db.models import OutboxModel
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")


def _read_outbox_token(db_url: str, event_type: str, field: str) -> str:
    """Достать сырой токен из payload события outbox (собственный engine на вызов)."""

    async def _run() -> str:
        engine = create_async_engine(db_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    select(OutboxModel.payload).where(OutboxModel.event_type == event_type)
                )
                payload = result.scalars().first()
                assert payload is not None, f"нет события {event_type} в outbox"
                return str(payload[field])
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_register_login_verify_flow(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        # регистрация
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "password123"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user"]["email"] == "user@example.com"
        assert body["user"]["email_verified"] is False
        assert body["access_token"]
        assert client.cookies.get("eventmind_access")

        # /me с cookie
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "user@example.com"

        # событие верификации записано в outbox → достаём сырой токен
        token = _read_outbox_token(
            settings.database_url, "user.registered", "verification_token"
        )
        verify = client.post("/api/v1/auth/verify-email", json={"token": token})
        assert verify.status_code == 200

        me2 = client.get("/api/v1/auth/me")
        assert me2.json()["email_verified"] is True


def test_duplicate_registration_conflict(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        payload = {"email": "dup@example.com", "password": "password123"}
        assert client.post("/api/v1/auth/register", json=payload).status_code == 201
        second = client.post("/api/v1/auth/register", json=payload)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "email_already_registered"


def test_login_wrong_password_401(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "a@example.com", "password": "password123"},
        )
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": "nope"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_credentials"


def test_me_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


def test_password_reset_flow(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "reset@example.com", "password": "password123"},
        )
        resp = client.post(
            "/api/v1/auth/password-reset", json={"email": "reset@example.com"}
        )
        assert resp.status_code == 200

        token = _read_outbox_token(
            settings.database_url, "password.reset_requested", "reset_token"
        )
        confirm = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "new_password": "brand-new-pass-1"},
        )
        assert confirm.status_code == 200

        # старый пароль больше не работает, новый — работает
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "reset@example.com", "password": "password123"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "reset@example.com", "password": "brand-new-pass-1"},
            ).status_code
            == 200
        )


def test_password_reset_unknown_email_silent(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        resp = client.post(
            "/api/v1/auth/password-reset", json={"email": "ghost@example.com"}
        )
        # одинаковый ответ — не раскрываем существование аккаунта
        assert resp.status_code == 200
