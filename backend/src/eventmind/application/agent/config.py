"""Ограничения агента на один ход (A3)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    max_steps: int = 5  # вызовов LLM на один ход
    max_tool_calls_per_step: int = 4
    max_tokens_per_turn: int = 24_000
    history_limit: int = 24  # сообщений истории, которые видит модель
    session_ttl_seconds: int = 3600
    message_max_chars: int = 2000
    tool_result_max_chars: int = 6000
    max_cards: int = 5
    temperature: float = 0.2
    # None — все зарегистрированные инструменты; иначе белый список имён
    allowed_tools: frozenset[str] | None = None
