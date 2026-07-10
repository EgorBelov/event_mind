"""Prometheus-метрики HTTP-слоя.

Базовый набор для M0: счётчик запросов и гистограмма латентности с
разбивкой по методу/маршруту/статусу. Специфичные метрики (латентность
рекомендаций, hit-rate кэша, токены/стоимость LLM, длина очереди,
доставки по каналам) добавляются в своих milestone'ах.

`prometheus_client` держит регистр процессно-глобальным, поэтому метрики
объявляются здесь как модульные синглтоны.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS_TOTAL = Counter(
    "eventmind_http_requests_total",
    "Всего HTTP-запросов",
    labelnames=("method", "path", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "eventmind_http_request_duration_seconds",
    "Латентность HTTP-запросов, сек",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── LLM Gateway ──────────────────────────────────────────────────────────────
LLM_REQUESTS_TOTAL = Counter(
    "eventmind_llm_requests_total",
    "Вызовы LLM по провайдеру и исходу",
    labelnames=("provider", "status"),  # status: success|error|skipped|breaker_open
)

LLM_TOKENS_TOTAL = Counter(
    "eventmind_llm_tokens_total",
    "Потреблённые токены LLM",
    labelnames=("provider", "direction"),  # direction: input|output
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "eventmind_llm_request_duration_seconds",
    "Латентность вызова LLM-провайдера, сек",
    labelnames=("provider",),
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 45.0),
)

# ── доставка уведомлений (M5) ─────────────────────────────────────────────────
NOTIFICATIONS_DELIVERED_TOTAL = Counter(
    "eventmind_notifications_delivered_total",
    "Доставки уведомлений по каналу и исходу",
    labelnames=("channel", "status"),  # status: success|error
)


def render_metrics() -> tuple[bytes, str]:
    """Отрендерить текущий срез метрик для эндпоинта `/metrics`."""
    return generate_latest(), CONTENT_TYPE_LATEST
