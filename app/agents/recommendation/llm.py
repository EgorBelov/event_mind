"""Groq LLM wrapper с автоматическим fallback на резервную модель.

При недоступности `settings.groq_model` (rate limit, отозванная версия,
квота) `llm.invoke` ловит исключение и повторяет запрос на
`settings.groq_fallback_model`. Это убирает каскадное падение LangGraph-цепочки.

Использование снаружи остаётся прежним: `from app.agents.recommendation.llm import llm`.
"""
from __future__ import annotations

import logging

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.core.config import settings

load_dotenv()

logger = logging.getLogger(__name__)


def _build_llm(model_name: str) -> ChatGroq:
    return ChatGroq(
        model=model_name,
        temperature=settings.groq_temperature,
        max_retries=settings.groq_max_retries,
    )


class _GroqWithFallback:
    """Тонкая обёртка с одинаковым контрактом ChatGroq.

    Делегирует invoke/bind_tools основной модели; при исключении —
    однократно повторяет на fallback-модели. Если упала и она — пробрасываем.
    """

    def __init__(self) -> None:
        self._primary = _build_llm(settings.groq_model)
        self._fallback = _build_llm(settings.groq_fallback_model)
        self._tools: list | None = None

    def _bound(self, base: ChatGroq):
        return base.bind_tools(self._tools) if self._tools else base

    def invoke(self, *args, **kwargs):
        try:
            return self._bound(self._primary).invoke(*args, **kwargs)
        except Exception as e:
            logger.warning(
                "Groq primary model %s failed: %s; falling back to %s",
                settings.groq_model, e, settings.groq_fallback_model,
            )
            return self._bound(self._fallback).invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        # Структурированный output живёт на primary; на fallback не дублируем,
        # пользователи этой ветки сами оборачивают в try/except.
        return self._primary.with_structured_output(*args, **kwargs)

    def bind_tools(self, tools):
        # Возвращаем новую обёртку с привязанными tools, чтобы цепочка
        # с инструментами тоже получала fallback.
        clone = _GroqWithFallback.__new__(_GroqWithFallback)
        clone._primary = self._primary
        clone._fallback = self._fallback
        clone._tools = tools
        return clone


llm = _GroqWithFallback()
