"""Распознавание серии события из title → `series_slug` (анти-флуд в выдаче).

Портировано из `legacy/app/recommender/series.py`. Простая эвристика без LLM:
снимаем «выпуск-маркеры» (#15, vol.2, годы, даты, римские в контексте) и
получаем стабильный slug, одинаковый у выпусков одной серии.
"""
from __future__ import annotations

import re
import unicodedata

# Маркеры выпуска. Римские числа ловим только в контексте (vol/часть/...),
# чтобы не путать со словами (ml, vi, mix).
_VOLUME_RE = re.compile(
    r"(?i)(?:^|[\s\-–—,])"
    r"(?:"
    r"\#\s?\d+|"
    r"vol\.?\s?(?:\d+|[ivxlcdm]+)|volume\s?\d+|no\.?\s?\d+|"
    r"№\s?\d+|"
    r"часть\s?(?:\d+|[ivxlcdm]+)|"
    r"выпуск\s?\d+|сезон\s?\d+|"
    r"ep\.?\s?\d+|episode\s?\d+|season\s?\d+|chapter\s?(?:\d+|[ivxlcdm]+)"
    r")"
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_RE = re.compile(r"\b\d{1,2}[./\- ](?:0?[1-9]|1[0-2])(?:[./\- ]\d{2,4})?\b")
_RUS_MONTH_RE = re.compile(
    r"(?i)\b(\d{1,2}\s+)?(?:янв(?:аря|\.)?|фев(?:раля|\.)?|мар(?:та|\.)?|апр(?:еля|\.)?|"
    r"мая|июн(?:я|\.)?|июл(?:я|\.)?|авг(?:уста|\.)?|сен(?:тября|\.)?|окт(?:ября|\.)?|"
    r"ноя(?:бря|\.)?|дек(?:абря|\.)?)\b"
)
_NON_SLUG = re.compile(r"[^a-z0-9а-я ]+")
_SPACES = re.compile(r"\s+")

_TR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(s: str) -> str:
    return "".join(_TR.get(ch, ch) for ch in s)


def compute_series_slug(title: str | None, city: str | None = None) -> str | None:
    """Стабильный slug серии или None, если серию выделить не удалось.

    `city` (если задан и не any/unknown) добавляется суффиксом — одинаковые
    серии в разных городах считаются разными.
    """
    if not title:
        return None
    s = unicodedata.normalize("NFKC", title).lower().strip()

    s = _VOLUME_RE.sub(" ", s)
    s = _DATE_RE.sub(" ", s)
    s = _RUS_MONTH_RE.sub(" ", s)
    s = _YEAR_RE.sub(" ", s)

    s = _translit(s)
    s = _NON_SLUG.sub(" ", s)
    s = _SPACES.sub(" ", s).strip()

    if len(s) <= 2:
        return None

    slug = s.replace(" ", "-")
    if city and city not in ("any", "unknown", ""):
        city_slug = _translit(city.lower())
        city_slug = _NON_SLUG.sub("", city_slug)
        if city_slug and city_slug not in slug:
            slug = f"{slug}--{city_slug}"

    return slug[:120]
