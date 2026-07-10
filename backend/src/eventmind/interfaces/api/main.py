"""Энтрипоинт API-процесса для uvicorn/gunicorn: `eventmind.interfaces.api.main:app`.

Fail-fast: до сборки приложения валидируем конфиг под контекст `api`
(отсутствие DATABASE_URL/REDIS_URL → выход с кодом 78).
"""
from __future__ import annotations

from eventmind.config import get_settings, validate_or_exit
from eventmind.interfaces.api.app import create_app

_settings = get_settings()
validate_or_exit(_settings, "api")

app = create_app(_settings)
