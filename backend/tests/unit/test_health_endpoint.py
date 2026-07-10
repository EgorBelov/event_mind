"""Unit: /health и /api/v1 отвечают без внешних зависимостей.

`/health` — liveness, не трогает Postgres/Redis, поэтому тестируется без
контейнеров. `/ready` (нужны реальные pg+redis) покрыт integration-тестом.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from eventmind.config import Settings
from eventmind.interfaces.api.app import create_app


def _client() -> TestClient:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        log_json=False,
    )
    return TestClient(create_app(settings))


def test_health_ok() -> None:
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers.get("X-Request-ID")


def test_api_v1_root() -> None:
    with _client() as client:
        resp = client.get("/api/v1/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "eventmind"
    assert body["api"] == "v1"


def test_metrics_exposed() -> None:
    with _client() as client:
        client.get("/health")  # сгенерировать хотя бы одну метрику
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"eventmind_http_requests_total" in resp.content
