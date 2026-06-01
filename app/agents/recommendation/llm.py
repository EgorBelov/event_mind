"""Groq LLM wrapper с автоматическим fallback на резервную модель.

При недоступности `settings.groq_model` (rate limit, отозванная версия,
квота) `llm.invoke` ловит исключение и повторяет запрос на
`settings.groq_fallback_model`. Это убирает каскадное падение LangGraph-цепочки.

Использование снаружи остаётся прежним: `from app.agents.recommendation.llm import llm`.
"""
from __future__ import annotations

import logging
import time

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.core.config import settings

load_dotenv()

logger = logging.getLogger(__name__)


# ─── Circuit-breaker ──────────────────────────────────────────────────────
# Защита от каскадных таймаутов: если Groq много раз подряд падает (rate-limit,
# 5xx, сеть), на cooldown_seconds открываем circuit — invoke сразу поднимает
# исключение, не дожидаясь httpx-таймаута. После cooldown пробуем снова.
class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 120.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # half-open: первый запрос после cooldown пройдёт
        return time.monotonic() - self._opened_at < self.cooldown_seconds

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            if self._opened_at is None:
                logger.warning(
                    "Groq circuit breaker OPEN after %d consecutive failures (cooldown %ss)",
                    self._consecutive_failures, self.cooldown_seconds,
                )
            self._opened_at = time.monotonic()


_breaker = _CircuitBreaker()


class CircuitOpenError(RuntimeError):
    """Поднимается, когда circuit-breaker открыт и invoke не пытается ходить в Groq."""


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

    ChatGroq строится ЛЕНИВО (при первом обращении), а не в __init__: иначе
    импорт модуля требовал бы GROQ_API_KEY (ломало тесты/CI без ключа и любой
    импорт без настроенного окружения). Ключ нужен только при реальном вызове.
    """

    def __init__(self, tools: list | None = None) -> None:
        self._tools = tools
        self._primary_llm: ChatGroq | None = None
        self._fallback_llm: ChatGroq | None = None

    @property
    def _primary(self) -> ChatGroq:
        if self._primary_llm is None:
            self._primary_llm = _build_llm(settings.groq_model)
        return self._primary_llm

    @property
    def _fallback(self) -> ChatGroq:
        if self._fallback_llm is None:
            self._fallback_llm = _build_llm(settings.groq_fallback_model)
        return self._fallback_llm

    def _bound(self, base: ChatGroq):
        return base.bind_tools(self._tools) if self._tools else base

    def invoke(self, *args, **kwargs):
        # Если circuit открыт — отрубаем быстро, не дожидаясь httpx-таймаута.
        # Caller'ы /copilot и /why уже завёрнуты в try/except и красиво
        # деградируют (rule-based ответ).
        if _breaker.is_open():
            raise CircuitOpenError("Groq circuit breaker is open — fast fail")

        try:
            res = self._bound(self._primary).invoke(*args, **kwargs)
            _breaker.record_success()
            return res
        except Exception as e:
            logger.warning(
                "Groq primary model %s failed: %s; falling back to %s",
                settings.groq_model, e, settings.groq_fallback_model,
            )
            try:
                res = self._bound(self._fallback).invoke(*args, **kwargs)
                _breaker.record_success()
                return res
            except Exception:
                # Оба упали — это сигнал для breaker'а.
                _breaker.record_failure()
                raise

    def with_structured_output(self, *args, **kwargs):
        # Структурированный output живёт на primary; на fallback не дублируем,
        # пользователи этой ветки сами оборачивают в try/except.
        return self._primary.with_structured_output(*args, **kwargs)

    def bind_tools(self, tools):
        # Новая обёртка с привязанными tools (тоже ленивая) — чтобы цепочка
        # с инструментами получала fallback.
        return _GroqWithFallback(tools=tools)


llm = _GroqWithFallback()
