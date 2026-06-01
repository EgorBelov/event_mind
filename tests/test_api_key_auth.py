"""Тесты shared-secret авторизации (ApiKeyMiddleware)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import install_middleware_and_handlers
from app.core.config import settings


@pytest.fixture
def app():
    app = FastAPI()
    install_middleware_and_handlers(app)

    @app.get("/protected")
    def _p():
        return {"ok": True}

    @app.get("/health")
    def _h():
        return {"status": "ok"}

    return app


def test_no_secret_means_open(app, monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", "")
    client = TestClient(app)
    r = client.get("/protected")
    assert r.status_code == 200


def test_secret_required(app, monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", "topsecret")
    client = TestClient(app)
    r = client.get("/protected")
    assert r.status_code == 401
    body = r.json()
    assert "X-API-Key" in body["detail"]


def test_secret_passes_with_correct_header(app, monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", "topsecret")
    client = TestClient(app)
    r = client.get("/protected", headers={"X-API-Key": "topsecret"})
    assert r.status_code == 200


def test_secret_rejected_on_mismatch(app, monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", "topsecret")
    client = TestClient(app)
    r = client.get("/protected", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_health_is_public_even_with_secret(app, monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", "topsecret")
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
