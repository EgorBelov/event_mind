"""OpenTelemetry-трейсинг: HTTP→app→БД, корреляция api↔worker.

Включается флагом `OTEL_ENABLED`. Экспорт — OTLP/HTTP на коллектор
(`OTEL_EXPORTER_OTLP_ENDPOINT`). Инструментируем FastAPI, SQLAlchemy, httpx.
Инструментирование идемпотентно (повторный вызов — no-op).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from eventmind.config import Settings

if TYPE_CHECKING:  # избегаем тяжёлого импорта в рантайме, если OTel выключен
    from fastapi import FastAPI


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    """Настроить провайдер трейсинга и инструментировать приложение.

    No-op при `otel_enabled=False`. Отсутствие эндпоинта не роняет процесс:
    используется консольный/батч-экспортёр по возможности.
    """
    if not settings.otel_enabled:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: settings.service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
