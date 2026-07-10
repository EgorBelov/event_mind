"""HTTP-клиент бота к API EventMind (bot↔api по внутреннему X-API-Key).

Бот не лезет в БД и не импортирует application/infrastructure — только HTTP.
Персональные вызовы идут в `/api/v1/bot/*` (резолв аккаунта по chat_id на
бэкенде), привязка — в `/api/v1/channels/telegram/confirm`, публичный поиск/
карточка — в `/api/v1/events/*`.
"""
from __future__ import annotations

from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(30.0)


class BotApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
            return await c.get(f"{self._base_url}{path}", params=params)

    async def _post(self, path: str, json: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
            return await c.post(f"{self._base_url}{path}", json=json)

    # ── привязка аккаунта ─────────────────────────────────────────────────────
    async def confirm_link(self, token: str, chat_id: str) -> tuple[bool, str]:
        """`/start <token>`: связать chat_id с аккаунтом. → (ok, message)."""
        try:
            r = await self._post(
                "/api/v1/channels/telegram/confirm",
                {"token": token, "chat_id": chat_id},
            )
        except httpx.HTTPError:
            return False, "Сервис недоступен, попробуйте позже."
        if r.status_code == 200:
            return True, r.json().get("detail", "Аккаунт привязан.")
        return False, _error_message(r, "Токен недействителен или истёк.")

    async def status(self, chat_id: str) -> bool:
        """Привязан ли chat_id к аккаунту."""
        try:
            r = await self._get("/api/v1/bot/status", {"chat_id": chat_id})
            r.raise_for_status()
            return bool(r.json().get("linked"))
        except httpx.HTTPError:
            return False

    # ── лента и feedback ──────────────────────────────────────────────────────
    async def recommendations(self, chat_id: str) -> list[dict[str, Any]]:
        try:
            r = await self._get("/api/v1/bot/recommendations", {"chat_id": chat_id})
            if r.status_code == 409:
                return []
            r.raise_for_status()
            data = r.json()
            return list(data) if isinstance(data, list) else []
        except httpx.HTTPError:
            return []

    async def interact(self, chat_id: str, event_id: int, action: str) -> bool:
        try:
            r = await self._post(
                "/api/v1/bot/interactions",
                {"chat_id": chat_id, "event_id": event_id, "action": action},
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # ── публичный поиск и карточка ────────────────────────────────────────────
    async def nl_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        try:
            r = await self._get(
                "/api/v1/events/nl-search", {"q": query, "limit": limit}
            )
            r.raise_for_status()
            data = r.json()
            return dict(data) if isinstance(data, dict) else {}
        except httpx.HTTPError:
            return {"relaxed": False, "results": []}

    async def event(self, event_id: int) -> dict[str, Any] | None:
        try:
            r = await self._get(f"/api/v1/events/{event_id}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return dict(r.json())
        except httpx.HTTPError:
            return None


def _error_message(response: httpx.Response, default: str) -> str:
    try:
        body = response.json()
        message = body.get("error", {}).get("message")
        if isinstance(message, str) and message:
            return message
    except (ValueError, AttributeError):
        pass
    return default
