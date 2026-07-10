"""Распознавание серии события из его title.

Рекуррентные митапы (Python MeetUp #14, ML Meetup vol.2, DevOps Days 2026)
сейчас либо дедуплицируются по cosine'у, либо плодятся как разные записи.
Идея — снять с title повторяющиеся «выпуск-маркеры» (номера, даты, города)
и получить **series_slug**: одинаковый у всех выпусков серии. Используется
для:
- анти-флуда в /recommendations (не показываем 3 выпуска подряд),
- группировки «похожих» событий,
- будущей дашборд-аналитики «топ серий».

Намеренно простая эвристика без LLM — стабильно работает на чёткой
повторяющейся пунктуации («#15», «vol.2», «2026»). Для крайних случаев
series_slug == None — это ОК (событие просто не попадёт в анти-флуд).
"""
from __future__ import annotations

import re
import unicodedata

# Маркеры выпуска, которые надо вычистить из title перед slug'ификацией.
# Намеренно НЕ ловим «голые» римские числа — слова `ml`, `vi`, `mix` дали бы
# ложные срабатывания. Римские распознаём только в контексте «vol/часть/...».
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

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")  # 1990..2099
_DATE_RE = re.compile(
    r"\b\d{1,2}[./\- ](?:0?[1-9]|1[0-2])(?:[./\- ]\d{2,4})?\b"
)
_RUS_MONTH_RE = re.compile(
    r"(?i)\b(\d{1,2}\s+)?(?:янв(?:аря|\.)?|фев(?:раля|\.)?|мар(?:та|\.)?|апр(?:еля|\.)?|"
    r"мая|июн(?:я|\.)?|июл(?:я|\.)?|авг(?:уста|\.)?|сен(?:тября|\.)?|окт(?:ября|\.)?|"
    r"ноя(?:бря|\.)?|дек(?:абря|\.)?)\b"
)
_NON_SLUG = re.compile(r"[^a-z0-9а-я ]+")
_SPACES = re.compile(r"\s+")

# Латинская транслитерация для slug'а. Простая, без iuliancode-зависимости.
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
    """Вернуть стабильный slug серии или None, если выделить серию не удалось.

    Идея: убрать из title все «выпуск-маркеры» и попробовать получить
    минимально короткий, но не пустой slug. Если осталось ≤ 2 символов
    (например, был «#15» и больше ничего) — вернём None.

    `city` опционален: если из title город не очевиден, добавляется как
    суффикс, чтобы одинаковые серии в разных городах считались разными
    (DevOps Days Moscow vs DevOps Days Berlin).
    """
    if not title:
        return None
    s = unicodedata.normalize("NFKC", title).lower().strip()

    # Чистим повторяющиеся маркеры.
    s = _VOLUME_RE.sub(" ", s)
    s = _DATE_RE.sub(" ", s)
    s = _RUS_MONTH_RE.sub(" ", s)
    s = _YEAR_RE.sub(" ", s)

    # Транслитерация и slug'ификация.
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
