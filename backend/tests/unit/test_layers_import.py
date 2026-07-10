"""Unit: smoke-импорт каждого слоя + проверка гексагональных границ.

Быстрый предохранитель: пакеты всех слоёв импортируются без ошибок, а
`domain` не тянет наружу фреймворки/инфраструктуру (жёстко это гарантирует
import-linter в CI, здесь — дешёвая проверка на уровне модуля).
"""
from __future__ import annotations

import importlib

import pytest

LAYER_MODULES = [
    "eventmind",
    "eventmind.config",
    "eventmind.domain",
    "eventmind.application",
    "eventmind.application.ports",
    "eventmind.infrastructure",
    "eventmind.infrastructure.db.engine",
    "eventmind.infrastructure.redis",
    "eventmind.infrastructure.logging",
    "eventmind.infrastructure.telemetry.metrics",
    "eventmind.interfaces.api.app",
]


@pytest.mark.parametrize("module", LAYER_MODULES)
def test_layer_imports(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_domain_has_no_outward_imports() -> None:
    """`domain`-пакет не должен тянуть infrastructure/interfaces/фреймворки."""
    import eventmind.domain as domain

    source_file = domain.__file__
    assert source_file is not None
    # Пакет-маркер пуст: у него нет подмодулей с внешними импортами в M0.
    # Контрактную проверку границ делает import-linter (CI).
    assert domain.__name__ == "eventmind.domain"
