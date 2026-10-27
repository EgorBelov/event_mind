"""Порт журнала агента: каждый вызов инструмента и итог хода.

Журнал нужен для отладки и для главы с оценкой (точность выбора инструментов,
число шагов, причины остановки). Сбой журнала не должен ломать ответ
пользователю — вызывающий код ловит исключения.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ToolCallStatus = Literal[
    "ok",  # выполнен
    "error",  # инструмент упал
    "invalid",  # аргументы не прошли валидацию
    "rejected",  # инструмент вне белого списка или запрещён правилом
    "pending",  # ждёт подтверждения пользователя
    "confirmed",  # подтверждён и выполнен
    "declined",  # пользователь отказался
]

StopReason = Literal[
    "answer",  # модель ответила текстом
    "confirmation",  # ждём подтверждения изменения
    "step_limit",  # исчерпан лимит шагов
    "token_limit",  # исчерпан лимит токенов на ход
    "llm_unavailable",  # LLM недоступна — интерфейс деградирует без агента
    "empty",  # пустое сообщение
    "resolved",  # ход = ответ на запрос подтверждения
]


@dataclass(slots=True)
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    step: int
    latency_ms: int = 0
    error: str | None = None


@dataclass(slots=True)
class AgentTurnRecord:
    user_id: int
    session_id: str
    channel: str  # bot | web | eval
    stop_reason: StopReason
    steps: int
    tokens: int
    latency_ms: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


class AgentJournal(Protocol):
    async def record(self, turn: AgentTurnRecord) -> None: ...
