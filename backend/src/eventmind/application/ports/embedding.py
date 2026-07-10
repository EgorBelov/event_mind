"""Порт `EmbeddingProvider` — векторизация текста (sentence-transformers за адаптером).

MiniLM-384 (multilingual). Батчинг и кэш — забота адаптера. Версия модели
нужна, чтобы инвалидировать эмбеддинги при смене модели.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def model_version(self) -> str: ...

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Векторизовать батч текстов (порядок сохраняется)."""
        ...

    async def embed_text(self, text: str) -> list[float]:
        """Векторизовать один текст."""
        ...
