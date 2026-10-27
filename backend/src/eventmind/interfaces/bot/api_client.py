"""HTTP-клиент бота к API EventMind (bot↔api по внутреннему X-API-Key).

Бот не лезет в БД и не импортирует application/infrastructure — только HTTP.
Персональные вызовы (включая диалоговый агент) идут в `/api/v1/bot/*` (резолв
аккаунта по chat_id на бэкенде), привязка веб-аккаунта — в `/api/v1/channels/telegram/confirm`,
публичный поиск/карточка — в `/api/v1/events/*`.

Ошибки сети/API не роняют бота: методы возвращают None / False / пустое, а
хендлер показывает человеческое сообщение.
"""
from __future__ import annotations

from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(30.0)
# Разбор профиля «о себе» и пересказ события идут через LLM — дольше обычного.
_LLM_TIMEOUT = httpx.Timeout(90.0)


class BotApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
            return await c.get(f"{self._base_url}{path}", params=params)

    async def _get_slow(self, path: str, params: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, headers=self._headers) as c:
            return await c.get(f"{self._base_url}{path}", params=params)

    async def _post(self, path: str, json: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
            return await c.post(f"{self._base_url}{path}", json=json)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        slow: bool = False,
    ) -> httpx.Response:
        timeout = _LLM_TIMEOUT if slow else _TIMEOUT
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as c:
            return await c.request(method, f"{self._base_url}{path}", json=json, params=params)

    # ── B1: регистрация прямо в боте ──────────────────────────────────────────
    async def register(self, chat_id: str) -> bool | None:
        """Создать аккаунт по chat_id (идемпотентно). True — создан, False — уже
        был, None — сервис недоступен."""
        try:
            r = await self._post("/api/v1/bot/register", {"chat_id": chat_id})
            data = _json_or_none(r)
        except httpx.HTTPError:
            return None
        return bool(data.get("created")) if data is not None else None

    # ── B2: профиль «о себе», настройки, сохранённое ──────────────────────────
    async def get_profile(self, chat_id: str) -> dict[str, Any] | None:
        try:
            return _json_or_none(
                await self._get("/api/v1/bot/profile", {"chat_id": chat_id})
            )
        except httpx.HTTPError:
            return None

    async def save_profile(
        self,
        chat_id: str,
        about: str,
        *,
        interests: list[str] | None = None,
        anti_interests: list[str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            r = await self._send(
                "PUT",
                "/api/v1/bot/profile",
                json={
                    "chat_id": chat_id,
                    "about": about,
                    "interests": interests,
                    "anti_interests": anti_interests,
                },
                slow=True,
            )
            return _json_or_none(r)
        except httpx.HTTPError:
            return None

    async def get_settings(self, chat_id: str) -> dict[str, Any] | None:
        try:
            return _json_or_none(
                await self._get("/api/v1/bot/settings", {"chat_id": chat_id})
            )
        except httpx.HTTPError:
            return None

    async def update_settings(self, chat_id: str, **fields: Any) -> dict[str, Any] | None:
        """PATCH настроек: city / preferred_format ("" — не важно), digest_frequency,
        quiet_hours_start / quiet_hours_end, clear_quiet_hours."""
        try:
            r = await self._send(
                "PATCH", "/api/v1/bot/settings", json={"chat_id": chat_id, **fields}
            )
            return _json_or_none(r)
        except httpx.HTTPError:
            return None

    async def saved(self, chat_id: str, *, offset: int = 0, limit: int = 5) -> dict[str, Any]:
        """{"items": [...], "total": N, "offset": K}; при ошибке — пустая страница."""
        empty: dict[str, Any] = {"items": [], "total": 0, "offset": offset}
        try:
            r = await self._get(
                "/api/v1/bot/saved", {"chat_id": chat_id, "offset": offset, "limit": limit}
            )
            return _json_or_none(r) or empty
        except httpx.HTTPError:
            return empty

    async def remove_saved(self, chat_id: str, event_id: int) -> bool:
        try:
            r = await self._send(
                "DELETE", f"/api/v1/bot/saved/{event_id}", params={"chat_id": chat_id}
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # ── B3: «📖 Подробнее» ────────────────────────────────────────────────────
    async def explain(self, chat_id: str, event_id: int) -> dict[str, Any] | None:
        """{"event": {...}, "summary": str, "summary_source": str, "reasons": [...]}."""
        try:
            return _json_or_none(
                await self._get_slow(
                    f"/api/v1/bot/events/{event_id}/explain", {"chat_id": chat_id}
                )
            )
        except httpx.HTTPError:
            return None

    # ── A4: диалоговый агент ──────────────────────────────────────────────────
    async def agent_message(self, chat_id: str, message: str) -> dict[str, Any] | None:
        """Реплика агенту → {"text", "events", "pending", "stop_reason", "degraded"}.
        None — агент недоступен (выключен, сеть, нет аккаунта): бот отвечает
        прямым поиском."""
        try:
            r = await self._send(
                "POST",
                "/api/v1/bot/agent/messages",
                json={"chat_id": chat_id, "message": message},
                slow=True,
            )
            return _json_or_none(r)
        except httpx.HTTPError:
            return None

    async def agent_confirm(
        self, chat_id: str, action_id: str, *, approve: bool
    ) -> dict[str, Any] | None:
        try:
            r = await self._send(
                "POST",
                "/api/v1/bot/agent/confirm",
                json={"chat_id": chat_id, "action_id": action_id, "approve": approve},
                slow=True,
            )
            return _json_or_none(r)
        except httpx.HTTPError:
            return None

    async def agent_reset(self, chat_id: str) -> bool:
        try:
            r = await self._send(
                "DELETE", "/api/v1/bot/agent/session", params={"chat_id": chat_id}
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

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


def _json_or_none(response: httpx.Response) -> dict[str, Any] | None:
    if response.status_code != 200:
        return None
    data = response.json()
    return dict(data) if isinstance(data, dict) else None
