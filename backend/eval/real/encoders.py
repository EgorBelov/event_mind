"""Энкодеры для сравнения (P1 №9 / H1) и дисковый кэш эмбеддингов.

Тексты строятся теми же функциями, что в приложении: событие —
`event_embedding_text`, персона — `profile_embedding_text` от извлечённого
профиля. Кэш — JSON {sha1(префикс+текст): вектор} на энкодер: повторные
прогоны не пересчитывают векторы, правка текста инвалидирует только его.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.real.data import CACHE_DIR

EncodeFn = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True, slots=True)
class EncoderSpec:
    key: str
    model: str
    # e5 обучен с префиксами: асимметричный поиск «профиль → событие».
    query_prefix: str = ""
    passage_prefix: str = ""


ENCODERS: dict[str, EncoderSpec] = {
    spec.key: spec
    for spec in (
        EncoderSpec("minilm", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        EncoderSpec("e5-base", "intfloat/multilingual-e5-base", "query: ", "passage: "),
        EncoderSpec("e5-large", "intfloat/multilingual-e5-large", "query: ", "passage: "),
        EncoderSpec("bge-m3", "BAAI/bge-m3"),
        EncoderSpec("user-bge-m3", "deepvk/USER-bge-m3"),
    )
}
# По умолчанию: текущий в приложении + два сильных мультиязычных.
DEFAULT_ENCODERS = ("minilm", "e5-base", "bge-m3")


def sentence_transformer_encode_fn(spec: EncoderSpec) -> EncodeFn:
    """EncodeFn поверх провайдера приложения (ленивая загрузка модели, нужен extra ml)."""
    from eventmind.infrastructure.embedding.minilm import SentenceTransformerEmbeddingProvider

    provider = SentenceTransformerEmbeddingProvider(model_name=spec.model, cache_size=0)

    async def encode(texts: list[str]) -> list[list[float]]:
        return await provider.embed_texts(texts)

    return encode


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, spec: EncoderSpec, *, cache_dir: Path = CACHE_DIR) -> None:
        self._spec = spec
        self._path = cache_dir / f"emb_{spec.key}.json"
        self._data: dict[str, list[float]] = (
            json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        )

    async def _get(
        self, texts: Sequence[str], prefix: str, encode: EncodeFn, batch_size: int
    ) -> list[list[float]]:
        keyed = [prefix + t for t in texts]
        missing = list(dict.fromkeys(k for k in keyed if _digest(k) not in self._data))
        for start in range(0, len(missing), batch_size):
            chunk = missing[start : start + batch_size]
            for text, vec in zip(chunk, await encode(chunk), strict=True):
                self._data[_digest(text)] = vec
        if missing:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data), encoding="utf-8")
        return [self._data[_digest(k)] for k in keyed]

    async def queries(
        self, texts: Sequence[str], encode: EncodeFn, *, batch_size: int = 64
    ) -> list[list[float]]:
        return await self._get(texts, self._spec.query_prefix, encode, batch_size)

    async def passages(
        self, texts: Sequence[str], encode: EncodeFn, *, batch_size: int = 64
    ) -> list[list[float]]:
        return await self._get(texts, self._spec.passage_prefix, encode, batch_size)
