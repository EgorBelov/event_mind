"""`SentenceTransformerEmbeddingProvider` — реализация порта `EmbeddingProvider`.

MiniLM-384 (multilingual). sentence-transformers импортируется ЛЕНИВО (тяжёлый
torch ставится через extra `ml`), а сам энкодер инъектируется — так кэш/батчинг
тестируются без torch (фейковый энкодер). Синхронный `encode` уводится в поток
(`asyncio.to_thread`), чтобы не блокировать event-loop.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> Any: ...


def _default_encoder_factory(model_name: str) -> Callable[[], Encoder]:
    def factory() -> Encoder:
        # Ленивый импорт: без extra `ml` модуль всё равно импортируется.
        from sentence_transformers import SentenceTransformer

        model: Encoder = SentenceTransformer(model_name)
        return model

    return factory


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dimension: int = 384,
        cache_size: int = 4096,
        encoder_factory: Callable[[], Encoder] | None = None,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._cache_size = cache_size
        self._encoder_factory = encoder_factory or _default_encoder_factory(model_name)
        self._encoder: Encoder | None = None
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_version(self) -> str:
        return self._model_name

    def _ensure_encoder(self) -> Encoder:
        if self._encoder is None:
            self._encoder = self._encoder_factory()
        return self._encoder

    def _cache_get(self, text: str) -> list[float] | None:
        vec = self._cache.get(text)
        if vec is not None:
            self._cache.move_to_end(text)
        return vec

    def _cache_put(self, text: str, vec: list[float]) -> None:
        self._cache[text] = vec
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        encoder = self._ensure_encoder()
        raw = encoder.encode(texts)
        return [[float(x) for x in row] for row in raw]

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        results: list[list[float] | None] = [self._cache_get(t) for t in texts]
        misses = [(i, t) for i, (t, r) in enumerate(zip(texts, results, strict=True)) if r is None]
        if misses:
            miss_texts = [t for _, t in misses]
            vectors = await asyncio.to_thread(self._encode_sync, miss_texts)
            for (idx, text), vec in zip(misses, vectors, strict=True):
                self._cache_put(text, vec)
                results[idx] = vec
        return [vec for vec in results if vec is not None]

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]
