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


def render_metrics() -> tuple[bytes, str]:
    """Отрендерить текущий срез метрик для эндпоинта `/metrics`."""
    return generate_latest(), CONTENT_TYPE_LATEST
