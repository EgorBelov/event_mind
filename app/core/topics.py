"""Справочники тем / форматов / городов / уровней.

EventMind стартует с курируемого «seed»-словаря (значения по умолчанию,
с которыми поставляется проект) и **расширяет словарь динамически**
по мере поступления новых событий из внешних источников
(Habr, raw JSON, AI-нормализатор и т. п.).

Правила:
- Темы хранятся в таблице `topics` — любое новое значение получает строку
  при первом упоминании (`ensure_topic`).
- Города / форматы / уровни хранятся как обычные строки на `events` и
  `users` — отдельной справочной таблицы нет, поэтому динамический список
  собирается через SELECT DISTINCT при запросе.
- Лукапы всегда возвращают результат: если код неизвестен, `humanize_code`
  собирает читаемый label из slug'а (например `saint_petersburg`
  → `Saint Petersburg`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Seed-словари — значения по умолчанию, с которыми проект поставляется.
# Это НЕ жёсткие whitelist'ы. Они задают человекочитаемые названия для
# известных кодов и предзаполняют UI-меню; парсер/нормализатор может
# свободно добавлять новые коды.
# ---------------------------------------------------------------------------

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
    "kazan": "Казань",
    "ekb": "Екатеринбург",
    "any": "Любой",
    "unknown": "Не указан",
}

SEED_LEVEL_LABELS: dict[str, str] = {
    "beginner": "Начинающий",
    "middle": "Middle",
    "advanced": "Advanced",
    "any": "Любой",
    "unknown": "Любой",
}


# Алиасы для обратной совместимости — старый код импортирует эти имена напрямую.
TOPIC_TITLES = SEED_TOPIC_TITLES
FORMAT_LABELS = SEED_FORMAT_LABELS
CITY_LABELS = SEED_CITY_LABELS
LEVEL_LABELS = SEED_LEVEL_LABELS

# Seed-список, оставлен только как fallback для промпта LLM.
# НЕ использовать как runtime-whitelist — вместо этого вызывать
# `get_allowed_topics(db)`.
SEED_TOPICS: list[str] = list(SEED_TOPIC_TITLES.keys())
ALLOWED_TOPICS = SEED_TOPICS  # legacy-алиас


# ---------------------------------------------------------------------------
# Slug-/label-хелперы
# ---------------------------------------------------------------------------

def slugify_code(value: str | None) -> str:
    """Привести произвольную строку к стабильному snake_case-slug'у.

    Примеры:
        "AI / ML" → "ai_ml"
        "Санкт-Петербург" → "санкт_петербург"  (кириллица сохраняется —
            slug'и здесь просто ключи, не URL)
        "  Some  Topic " → "some_topic"
    """
    if not value:
        return ""
    s = value.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[/\\,;:]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def humanize_code(code: str | None) -> str:
    """Превратить `some_code` в `Some Code` для отображения в UI."""
    if not code:
        return ""
    return code.replace("_", " ").replace("-", " ").strip().title()


def topic_title(code: str | None) -> str:
    """Вернуть человекочитаемое название темы; fallback — humanize_code."""
    if not code:
        return ""
    return SEED_TOPIC_TITLES.get(code) or humanize_code(code)


def format_label(code: str | None) -> str:
    if not code:
        return ""
    return SEED_FORMAT_LABELS.get(code) or humanize_code(code)


def city_label(code: str | None) -> str:
    if not code:
        return ""
    return SEED_CITY_LABELS.get(code) or humanize_code(code)


def level_label(code: str | None) -> str:
    if not code:
        return ""
    return SEED_LEVEL_LABELS.get(code) or humanize_code(code)


# ---------------------------------------------------------------------------
# Динамические лукапы словаря — читаем из базы.
# ---------------------------------------------------------------------------

def get_known_topic_codes(db) -> list[str]:
    """Все известные системе коды тем: seed + всё, что лежит в таблице `topics`."""
    from app.db.models.topic import Topic

    db_codes = [t.code for t in db.query(Topic).all()]
    return _merge_preserve_order(SEED_TOPICS, db_codes)


def get_allowed_topics(db=None) -> list[str]:
    """Темы, которые нормализатор и анализатор bio должны считать валидными.

    Если передан `db` — возвращается **динамический** набор (seed + всё, что
    уже сохранено). Без `db` — только seed (статический fallback).
    """
    if db is None:
        return list(SEED_TOPICS)
    return get_known_topic_codes(db)


def get_known_cities(db) -> list[str]:
    """Seed-города + DISTINCT-значения city, реально присутствующие в БД."""
    from app.db.models.event import Event
    from app.db.models.user import User

    event_cities = [row[0] for row in db.query(Event.city).distinct().all() if row[0]]
    user_cities = [row[0] for row in db.query(User.city).distinct().all() if row[0]]
    return _merge_preserve_order(list(SEED_CITY_LABELS.keys()), event_cities + user_cities)


def get_known_formats(db) -> list[str]:
    from app.db.models.event import Event
    from app.db.models.user import User

    event_formats = [row[0] for row in db.query(Event.format).distinct().all() if row[0]]
    user_formats = [
        row[0] for row in db.query(User.preferred_format).distinct().all() if row[0]
    ]
    return _merge_preserve_order(
        list(SEED_FORMAT_LABELS.keys()), event_formats + user_formats
    )


def get_known_levels(db) -> list[str]:
    from app.db.models.event import Event

    event_levels = [row[0] for row in db.query(Event.level).distinct().all() if row[0]]
    return _merge_preserve_order(list(SEED_LEVEL_LABELS.keys()), event_levels)


def ensure_topic(db, code: str) -> None:
    """Создать строку в `topics` для `code`, если её ещё нет.

    Используется нормализатором / event-service, когда появляется новая тема.
    """
    if not code:
        return
    from app.db.models.topic import Topic

    if db.query(Topic).filter(Topic.code == code).first():
        return
    db.add(Topic(code=code, title=topic_title(code)))
    db.flush()


# ---------------------------------------------------------------------------
# Внутренние хелперы
# ---------------------------------------------------------------------------

def _merge_preserve_order(*sources: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        for item in src:
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
    return out
