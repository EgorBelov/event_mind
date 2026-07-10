"""Таксономия событий: slug'и, канонизация города, seed-словари.

Портировано из `legacy/app/core/topics.py` — только чистые функции (без БД).
Seed-словари задают человекочитаемые лейблы и предпочтительные значения для
промпта нормализатора; это НЕ жёсткие whitelist'ы — словарь растёт динамически.
"""
from __future__ import annotations

import re

SEED_TOPIC_TITLES: dict[str, str] = {
    "ai_ml": "AI / ML",
    "data_science": "Data Science",
    "business_analytics": "Бизнес-аналитика",
    "backend": "Backend",
    "frontend": "Frontend",
    "product": "Product",
    "cybersecurity": "Кибербезопасность",
    "devops": "DevOps",
}

SEED_FORMAT_LABELS: dict[str, str] = {
    "online": "online",
    "offline": "offline",
    "hybrid": "hybrid",
    "any": "Любой",
    "unknown": "unknown",
}

SEED_CITY_LABELS: dict[str, str] = {
    "moscow": "Москва",
    "spb": "Санкт-Петербург",
    "novosibirsk": "Новосибирск",
    "ekb": "Екатеринбург",
    "kazan": "Казань",
    "nizhny_novgorod": "Нижний Новгород",
    "chelyabinsk": "Челябинск",
    "samara": "Самара",
    "ufa": "Уфа",
    "rostov": "Ростов-на-Дону",
    "krasnodar": "Краснодар",
    "voronezh": "Воронеж",
    "perm": "Пермь",
    "tomsk": "Томск",
    "innopolis": "Иннополис",
    "sochi": "Сочи",
    "vladivostok": "Владивосток",
    "any": "Любой",
    "unknown": "Не указан",
}

CANONICAL_CITIES: frozenset[str] = frozenset(
    code for code in SEED_CITY_LABELS if code not in {"any", "unknown"}
)

# Алиасы городов: схлопывают транслитерации/сокращения к каноническому slug'у.
CITY_ALIASES: dict[str, str] = {
    "msk": "moscow",
    "moskva": "moscow",
    "moscow_city": "moscow",
    "saint_petersburg": "spb",
    "sankt_peterburg": "spb",
    "st_petersburg": "spb",
    "piter": "spb",
    "saint_p": "spb",
    "leningrad": "spb",
    "ekaterinburg": "ekb",
    "yekaterinburg": "ekb",
    "yekb": "ekb",
    "ekat": "ekb",
    "nsk": "novosibirsk",
    "novosib": "novosibirsk",
    "nn": "nizhny_novgorod",
    "nizhniy_novgorod": "nizhny_novgorod",
    "n_novgorod": "nizhny_novgorod",
    "nizhny": "nizhny_novgorod",
    "kazan_city": "kazan",
    "chel": "chelyabinsk",
    "rostov_on_don": "rostov",
    "rostov_na_donu": "rostov",
    "vladik": "vladivostok",
}

SEED_LEVEL_LABELS: dict[str, str] = {
    "beginner": "Начинающий",
    "middle": "Middle",
    "advanced": "Advanced",
    "any": "Любой",
    "unknown": "Любой",
}

SEED_TOPICS: list[str] = list(SEED_TOPIC_TITLES.keys())


def slugify_code(value: str | None) -> str:
    """Привести произвольную строку к стабильному snake_case-slug'у.

    "AI / ML" → "ai_ml"; "  Some  Topic " → "some_topic". Кириллица
    сохраняется (slug'и — ключи словаря, не URL).
    """
    if not value:
        return ""
    s = value.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[/\\,;:]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def humanize_code(code: str | None) -> str:
    """`some_code` → `Some Code` для UI."""
    if not code:
        return ""
    return code.replace("_", " ").replace("-", " ").strip().title()


def topic_title(code: str | None) -> str:
    if not code:
        return ""
    return SEED_TOPIC_TITLES.get(code) or humanize_code(code)


def city_label(code: str | None) -> str:
    if not code:
        return ""
    return SEED_CITY_LABELS.get(code) or humanize_code(code)


def canonicalize_city(code: str | None) -> str:
    """Схлопнуть slug города к каноническому (msk→moscow, piter→spb).

    Экзотика вне списка (omsk, barnaul) остаётся как есть — open-domain.
    """
    if not code:
        return ""
    slug = slugify_code(code)
    if not slug:
        return ""
    return CITY_ALIASES.get(slug, slug)
