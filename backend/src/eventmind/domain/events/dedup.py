"""Семантическая дедупликация событий между источниками (P1 №8).

Одно и то же событие приходит с разных сайтов (Habr, KudaGo, RSS) с разными
URL и формулировками — идемпотентность по `source_url` его не ловит.
Решение по паре «новое событие × ближайшее по эмбеддингу существующее»:

- даты обоих известны и расходятся больше чем на `max_days_apart` → разные;
- оба города известны и разные → разные (одна серия в разных городах);
- cosine ≥ `duplicate_similarity` → дубль;
- cosine в «серой зоне» [`uncertain_similarity`, `duplicate_similarity`):
  дубль, если заметно совпадают заголовки; иначе — «не уверен» (решает
  LLM-арбитр, если он включён; без арбитра событие сохраняется — лучше дубль
  в ленте, чем потерянное событие).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DedupVerdict = Literal["duplicate", "uncertain", "distinct"]

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_UNKNOWN_CITIES = frozenset({"", "any", "unknown"})


@dataclass(frozen=True, slots=True)
class DedupPolicy:
    duplicate_similarity: float = 0.92
    uncertain_similarity: float = 0.85
    title_overlap: float = 0.6
    max_days_apart: int = 1


@dataclass(frozen=True, slots=True)
class DedupCandidate:
    """Существующее событие, близкое по эмбеддингу к новому."""

    event_id: int
    title: str
    description: str
    city: str
    start_at: datetime | None
    similarity: float  # cosine с новым событием


def title_overlap(a: str, b: str) -> float:
    """Жаккар по словам длиннее 2 символов (без регистра)."""
    wa = {w for w in _WORD_RE.findall(a.casefold()) if len(w) > 2}
    wb = {w for w in _WORD_RE.findall(b.casefold()) if len(w) > 2}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def judge_duplicate(
    *,
    title: str,
    city: str,
    start_at: datetime | None,
    candidate: DedupCandidate,
    policy: DedupPolicy,
) -> DedupVerdict:
    if start_at is not None and candidate.start_at is not None:
        days = abs((start_at - candidate.start_at).total_seconds()) / 86400
        if days > policy.max_days_apart:
            return "distinct"
    known = city not in _UNKNOWN_CITIES and candidate.city not in _UNKNOWN_CITIES
    if known and city != candidate.city:
        return "distinct"
    if candidate.similarity >= policy.duplicate_similarity:
        return "duplicate"
    if candidate.similarity >= policy.uncertain_similarity:
        if title_overlap(title, candidate.title) >= policy.title_overlap:
            return "duplicate"
        return "uncertain"
    return "distinct"
