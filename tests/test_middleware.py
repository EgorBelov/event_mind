"""Тесты RequestLogMiddleware и exception handler'а."""
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.middleware import install_middleware_and_handlers


@pytest.fixture
def app():
    app = FastAPI()
    install_middleware_and_handlers(app)

    @app.get("/ok")
    def _ok():
        return {"ok": True}

    @app.get("/missing")
    def _missing():
        raise HTTPException(status_code=404, detail="User not found")

    @app.get("/boom")
    def _boom():
        raise RuntimeError("kaboom")

    return app


def test_ok_returns_request_id(app):
    client = TestClient(app)
    r = client.get("/ok")
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers


def test_request_id_passthrough(app):
    client = TestClient(app)
    r = client.get("/ok", headers={"X-Request-ID": "client-abc"})
    assert r.headers["X-Request-ID"] == "client-abc"


def test_404_is_warning_not_error(app, caplog):
    client = TestClient(app)
    with caplog.at_level(logging.DEBUG, logger="eventmind.access"):
        r = client.get("/missing")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "User not found"
    assert "request_id" in body
    # уровень — WARNING (а не ERROR с traceback)
    levels = [rec.levelname for rec in caplog.records if rec.name == "eventmind.access"]
    assert "WARNING" in levels
    assert "ERROR" not in levels
