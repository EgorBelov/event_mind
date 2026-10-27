"""Состояние диалога с агентом: история, показанные события, отложенное действие.

Хранится в кэше (Redis) с TTL: это не память пользователя (она — в модели
пользователя), а контекст текущего разговора. Потеря сессии безопасна —
пользователь просто начинает диалог заново.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from eventmind.application.ports.cache import Cache
from eventmind.application.ports.llm import LLMMessage, ToolCall

_logger = structlog.get_logger("eventmind.agent")

MAX_SHOWN = 60


@dataclass(slots=True)
class PendingAction:
    """Изменение, которое агент предложил и которое ждёт подтверждения."""

    id: str
    tool: str
    arguments: dict[str, Any]
    description: str


@dataclass(slots=True)
class AgentSession:
    session_id: str
    messages: list[LLMMessage] = field(default_factory=list)
    shown_event_ids: list[int] = field(default_factory=list)
    pending: PendingAction | None = None

    def remember_shown(self, event_ids: list[int]) -> None:
        for event_id in event_ids:
            if event_id in self.shown_event_ids:
                self.shown_event_ids.remove(event_id)
            self.shown_event_ids.append(event_id)
        del self.shown_event_ids[:-MAX_SHOWN]


def trim_history(messages: list[LLMMessage], limit: int) -> list[LLMMessage]:
    """Последние `limit` сообщений, начиная с реплики пользователя: обрезка
    посередине шага оставила бы ответы инструментов без их вызова, а такую
    историю провайдеры отвергают."""
    if len(messages) <= limit:
        return list(messages)
    tail = messages[-limit:]
    for i, message in enumerate(tail):
        if message.role == "user":
            return tail[i:]
    return []


def _message_to_dict(m: LLMMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


def _message_from_dict(raw: dict[str, Any]) -> LLMMessage:
    return LLMMessage(
        role=raw["role"],
        content=str(raw.get("content", "")),
        tool_calls=tuple(
            ToolCall(id=c["id"], name=c["name"], arguments=dict(c.get("arguments") or {}))
            for c in raw.get("tool_calls") or []
        ),
        tool_call_id=raw.get("tool_call_id"),
    )


def dump_session(session: AgentSession) -> str:
    pending = session.pending
    return json.dumps(
        {
            "session_id": session.session_id,
            "messages": [_message_to_dict(m) for m in session.messages],
            "shown": session.shown_event_ids,
            "pending": (
                {
                    "id": pending.id,
                    "tool": pending.tool,
                    "arguments": pending.arguments,
                    "description": pending.description,
                }
                if pending
                else None
            ),
        },
        ensure_ascii=False,
    )


def load_session(raw: str) -> AgentSession:
    data = json.loads(raw)
    pending = data.get("pending")
    return AgentSession(
        session_id=str(data["session_id"]),
        messages=[_message_from_dict(m) for m in data.get("messages") or []],
        shown_event_ids=[int(i) for i in data.get("shown") or []],
        pending=PendingAction(**pending) if pending else None,
    )


def _session_key(user_id: int) -> str:
    return f"agent:v1:{user_id}"


def new_id() -> str:
    return uuid.uuid4().hex


class AgentSessionStore:
    def __init__(
        self,
        cache: Cache,
        *,
        ttl_seconds: int,
        history_limit: int,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        self._cache = cache
        self._ttl = ttl_seconds
        self._history_limit = history_limit
        self._new_id = id_factory

    async def load(self, user_id: int) -> AgentSession:
        raw = await self._cache.get(_session_key(user_id))
        if raw:
            try:
                return load_session(raw)
            except (ValueError, KeyError, TypeError) as exc:
                _logger.warning("agent_session_corrupted", user=user_id, error=str(exc))
        return AgentSession(session_id=self._new_id())

    async def save(self, user_id: int, session: AgentSession) -> None:
        session.messages = trim_history(session.messages, self._history_limit)
        await self._cache.set(_session_key(user_id), dump_session(session), ttl_seconds=self._ttl)

    async def reset(self, user_id: int) -> None:
        await self._cache.delete(_session_key(user_id))
