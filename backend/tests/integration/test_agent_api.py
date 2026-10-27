"""Integration: диалоговый агент через API (веб — JWT, бот — chat_id + API-key).

LLM подменяется сценарием (`container.llm`), остальное настоящее: Postgres,
Redis-сессия, журнал agent_tool_calls. Проверяем A5-критерий: изменение
профиля из чата после «Да» видно в `/users/me/profile`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from eventmind.application.ports.llm import (
    LLMMessage,
    LLMUnavailable,
    LLMUsage,
    ToolCall,
    ToolSpec,
    ToolStep,
)
from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app

pytestmark = pytest.mark.usefixtures("clean_tables")

CHAT_ID = "424242"


class ScriptedLLM:
    def __init__(self, steps: Sequence[ToolStep | Exception]) -> None:
        self.steps = list(steps)

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolStep:
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _call(name: str, **args: Any) -> ToolStep:
    return ToolStep(
        text="",
        tool_calls=(ToolCall(id="c1", name=name, arguments=args),),
        provider="fake",
        usage=LLMUsage(5, 5),
    )


def _answer(value: str) -> ToolStep:
    return ToolStep(text=value, tool_calls=(), provider="fake")


def _use_llm(client: TestClient, steps: Sequence[ToolStep | Exception]) -> None:
    client.app.state.container.llm = ScriptedLLM(steps)  # type: ignore[attr-defined]


def _register(client: TestClient, email: str) -> None:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    assert resp.status_code == 201, resp.text


async def _journal_statuses(settings: Settings) -> list[tuple[str, str]]:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT tool, status FROM agent_tool_calls ORDER BY id"))
            return [(r[0], r[1]) for r in rows.all()]
    finally:
        await engine.dispose()


def test_web_profile_change_from_chat_is_visible_in_profile(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "agent@example.com")
        _use_llm(client, [_call("update_profile", add_interests=["ai_ml"], add_goals=["в ML"])])

        reply = client.post("/api/v1/agent/messages", json={"message": "хочу в ML"})
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["stop_reason"] == "confirmation" and body["pending"] is not None
        # до подтверждения профиль не меняется
        assert client.get("/api/v1/users/me/profile").json()["interests"] == []

        done = client.post(
            "/api/v1/agent/confirm",
            json={"action_id": body["pending"]["id"], "approve": True},
        )
        assert done.status_code == 200 and done.json()["text"].startswith("✅")
        profile = client.get("/api/v1/users/me/profile").json()
        assert profile["interests"] == ["ai_ml"] and profile["goals"] == ["в ML"]

        history = client.get("/api/v1/agent/session").json()
        assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
        assert client.delete("/api/v1/agent/session").status_code == 200
        assert client.get("/api/v1/agent/session").json()["messages"] == []

    assert asyncio.run(_journal_statuses(settings)) == [
        ("update_profile", "pending"),
        ("update_profile", "confirmed"),
    ]


def test_web_agent_degrades_without_llm(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _register(client, "nollm@example.com")
        _use_llm(client, [LLMUnavailable("down")])
        body = client.post("/api/v1/agent/messages", json={"message": "что по Go?"}).json()
        assert body["degraded"] is True and body["stop_reason"] == "llm_unavailable"


def test_web_agent_requires_auth(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/agent/messages", json={"message": "x"}).status_code == 401


def test_agent_disabled_returns_503(settings: Settings) -> None:
    disabled = settings.model_copy(update={"agent_enabled": False})
    with TestClient(create_app(disabled)) as client:
        _register(client, "off@example.com")
        resp = client.post("/api/v1/agent/messages", json={"message": "x"})
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "agent_disabled"


def test_bot_agent_flow(settings: Settings) -> None:
    key = {"X-API-Key": settings.api_shared_secret}
    with TestClient(create_app(settings)) as client:
        # без аккаунта — 409, бот создаёт аккаунт и повторяет
        resp = client.post(
            "/api/v1/bot/agent/messages", json={"chat_id": CHAT_ID, "message": "x"}, headers=key
        )
        assert resp.status_code == 409
        assert client.post(
            "/api/v1/bot/register", json={"chat_id": CHAT_ID}, headers=key
        ).status_code == 200

        _use_llm(client, [_call("search_events", topics=["golang"]), _answer("Пока пусто")])
        body = client.post(
            "/api/v1/bot/agent/messages",
            json={"chat_id": CHAT_ID, "message": "Go в Перми"},
            headers=key,
        ).json()
        assert body["text"] == "Пока пусто" and body["events"] == []

        _use_llm(client, [_call("update_settings", city="Пермь")])
        pending = client.post(
            "/api/v1/bot/agent/messages",
            json={"chat_id": CHAT_ID, "message": "я в Перми"},
            headers=key,
        ).json()["pending"]
        done = client.post(
            "/api/v1/bot/agent/confirm",
            json={"chat_id": CHAT_ID, "action_id": pending["id"], "approve": True},
            headers=key,
        ).json()
        assert done["text"].startswith("✅")
        settings_resp = client.get(
            "/api/v1/bot/settings", params={"chat_id": CHAT_ID}, headers=key
        ).json()
        assert settings_resp["city"] == "perm"

        reset = client.delete(
            "/api/v1/bot/agent/session", params={"chat_id": CHAT_ID}, headers=key
        )
        assert reset.status_code == 200
