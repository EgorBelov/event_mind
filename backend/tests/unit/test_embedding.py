"""Unit: EmbeddingProvider — кэш, батчинг, порядок (фейковый энкодер, без torch)."""
from __future__ import annotations

import asyncio
import time

from eventmind.infrastructure.embedding.minilm import SentenceTransformerEmbeddingProvider


class FakeEncoder:
    """Детерминированный энкодер: вектор = [len(text), hash%10, 0.0]. Считает вызовы."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), float(sum(map(ord, t)) % 10), 0.0] for t in texts]


def _provider(encoder: FakeEncoder, **kw: object) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        model_name="fake-model", dimension=3, encoder_factory=lambda: encoder, **kw
    )


async def test_embed_text_and_metadata() -> None:
    enc = FakeEncoder()
    p = _provider(enc)
    vec = await p.embed_text("hello")
    assert vec == [5.0, float(sum(map(ord, "hello")) % 10), 0.0]
    assert p.dimension == 3
    assert p.model_version == "fake-model"


async def test_cache_avoids_recompute() -> None:
    enc = FakeEncoder()
    p = _provider(enc)
    await p.embed_text("repeat")
    await p.embed_text("repeat")
    # второй вызов обслужен из кэша — энкодер дёрнут один раз
    assert len(enc.calls) == 1


async def test_batch_only_encodes_misses_and_preserves_order() -> None:
    enc = FakeEncoder()
    p = _provider(enc)
    await p.embed_text("a")  # прогреть кэш для "a"
    enc.calls.clear()

    result = await p.embed_texts(["a", "bb", "ccc"])
    # энкодеру ушли только промахи "bb","ccc" (а не "a")
    assert enc.calls == [["bb", "ccc"]]
    # порядок соответствует входу
    assert result[0] == [1.0, float(sum(map(ord, "a")) % 10), 0.0]
    assert result[1][0] == 2.0
    assert result[2][0] == 3.0


async def test_lru_eviction() -> None:
    enc = FakeEncoder()
    p = _provider(enc, cache_size=2)
    await p.embed_text("x")
    await p.embed_text("y")
    await p.embed_text("z")  # вытесняет "x"
    enc.calls.clear()
    await p.embed_text("x")  # снова считается (был вытеснен)
    assert enc.calls == [["x"]]


async def test_encoder_loaded_once_under_concurrent_first_calls() -> None:
    created: list[FakeEncoder] = []

    def slow_factory() -> FakeEncoder:
        time.sleep(0.05)  # «загрузка модели» — даём потокам пересечься
        enc = FakeEncoder()
        created.append(enc)
        return enc

    p = SentenceTransformerEmbeddingProvider(
        model_name="fake-model", dimension=3, encoder_factory=slow_factory
    )
    await asyncio.gather(*(p.embed_text(f"t{i}") for i in range(5)))
    assert len(created) == 1
