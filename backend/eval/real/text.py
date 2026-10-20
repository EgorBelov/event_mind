"""Лексические базовые линии: токенизация, TF-IDF (cosine) и Okapi BM25.

Чистый Python без внешних зависимостей. Для русского — грубый усечённый
стемминг (префикс 6 символов): стандартный приём для слабой лексической
базовой линии, против которой сравниваются семантические методы.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[a-zа-яё0-9+#]+")
_CYRILLIC_RE = re.compile(r"[а-яё]")
_STEM_LEN = 6

_STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
    по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
    ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом
    себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам
    чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому
    этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были
    куда зачем всех никогда можно при наконец два об другой хоть после над
    больше тот через эти нас про всего них какая много разве три эту моя впрочем
    хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда
    конечно всю между это также который которые очень
    the a an and or of to in on for with is are be by at as from this that it
    """.split()
)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower().replace("ё", "е")):
        if len(tok) < 2 or tok in _STOPWORDS:
            continue
        if _CYRILLIC_RE.search(tok) and len(tok) > _STEM_LEN:
            tok = tok[:_STEM_LEN]
        tokens.append(tok)
    return tokens


class TfidfIndex:
    """TF-IDF с сублинейным tf и сглаженным idf; документы l2-нормированы."""

    def __init__(self, documents: Sequence[str]) -> None:
        tokenized = [tokenize(d) for d in documents]
        n = len(tokenized)
        df: Counter[str] = Counter()
        for toks in tokenized:
            df.update(set(toks))
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self._docs = [self._vector(toks) for toks in tokenized]

    def _vector(self, tokens: Sequence[str]) -> dict[str, float]:
        counts = Counter(tokens)
        vec = {
            t: (1.0 + math.log(c)) * self._idf[t] for t, c in counts.items() if t in self._idf
        }
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {t: v / norm for t, v in vec.items()} if norm > 0 else {}

    def scores(self, query: str) -> list[float]:
        q = self._vector(tokenize(query))
        return [sum(w * doc.get(t, 0.0) for t, w in q.items()) for doc in self._docs]


class Bm25Index:
    """Okapi BM25 (k1=1.5, b=0.75)."""

    def __init__(self, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs = [Counter(tokenize(d)) for d in documents]
        self._lens = [sum(c.values()) for c in self._docs]
        n = len(self._docs)
        self._avgdl = (sum(self._lens) / n) if n else 0.0
        df: Counter[str] = Counter()
        for counts in self._docs:
            df.update(counts.keys())
        self._idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        out: list[float] = []
        for counts, length in zip(self._docs, self._lens, strict=True):
            norm = self._k1 * (1.0 - self._b + self._b * length / (self._avgdl or 1.0))
            score = 0.0
            for t in terms:
                tf = counts.get(t, 0)
                if tf:
                    score += self._idf.get(t, 0.0) * tf * (self._k1 + 1.0) / (tf + norm)
            out.append(score)
        return out
