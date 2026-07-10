"""Timepad — открытый JSON-API крупнейшего русского агрегатора мероприятий.

Документация: https://dev.timepad.ru/

Преимущество перед RSS/Habr: организаторы сами заполняют поля
`name/starts_at/city/categories`, поэтому почти нет non_it отсева и
LLM-нормализатору остаётся лёгкий маппинг полей вместо парса текста.

Требуется bearer-токен (бесплатно, 2 мин регистрации на dev.timepad.ru):
складывается в `.env` как `TIMEPAD_TOKEN`. Без токена source молча
возвращает пустой список — `load_all_events` его пропускает, как и
не настроенные luma/meetup.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.utils import utcnow_naive

logger = get_logger(__name__)

API = "https://api.timepad.ru/v1/events.json"
# Поля минимальные, но достаточные для нашего нормализатора. Полный
# description_html запрашиваем, чтобы у LLM был контекст; короткое
# description_short — на случай если html пуст.
_FIELDS = ",".join([
    "id", "name", "starts_at", "ends_at", "url",
    "description_short", "description_html",
    "location", "categories",
])


def _build_raw_description(item: dict) -> str:
    """Собрать «сырое описание» под наш нормализатор: текст + структурные поля."""
    descr = item.get("description_html") or item.get("description_short") or ""
    location = item.get("location") or {}
    city = location.get("city") if isinstance(location, dict) else None
    address = location.get("address") if isinstance(location, dict) else None
    country = location.get("country") if isinstance(location, dict) else None

    cats = item.get("categories") or []
    cat_names = [c.get("name") for c in cats if isinstance(c, dict) and c.get("name")]

    extra_lines: list[str] = []
    if item.get("starts_at"):
        extra_lines.append(f"Дата начала: {item['starts_at']}")
    if item.get("ends_at"):
        extra_lines.append(f"Дата окончания: {item['ends_at']}")
    if city:
        extra_lines.append(f"Город: {city}")
    if address:
        extra_lines.append(f"Адрес: {address}")
    if country and not city:
        extra_lines.append(f"Страна: {country}")
    if cat_names:
        extra_lines.append(f"Категории Timepad: {', '.join(cat_names)}")

    raw = descr.strip()
    if extra_lines:
        raw += "\n\n" + "\n".join(extra_lines)
    return raw.strip()


def fetch_timepad_events(limit: int = 20) -> list[dict]:
    """Скачать события из Timepad. Возвращает [{title, raw_description, source_url}]."""
    token = (getattr(settings, "timepad_token", "") or "").strip()
    if not token:
        logger.info("Timepad: TIMEPAD_TOKEN не задан — источник пропущен.")
        return []

    params: dict[str, str | int] = {
        "limit": min(max(1, int(limit)), 100),
        "fields": _FIELDS,
        # ISO-дата «начиная с сейчас» — фильтр прошедших событий ещё на стороне
        # API, чтобы не тратить квоту LLM на бесполезное.
        "starts_at_min": utcnow_naive().strftime("%Y-%m-%d"),
        "sort": "+starts_at",  # ближайшие в начале
    }
    categories = (getattr(settings, "timepad_category_ids", "") or "").strip()
    if categories:
        params["category_ids"] = categories
    cities = (getattr(settings, "timepad_cities", "") or "").strip()
    if cities:
        params["cities"] = cities

    try:
        r = httpx.get(
            API,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "EventMind/1.0",
            },
            timeout=15.0,
        )
    except Exception as e:
        logger.warning("Timepad fetch failed: %s", e)
        return []

    if r.status_code in (401, 403):
        # Чаще всего — невалидный/просроченный токен. Не валим load_all_events,
        # просто помечаем источник как пропущенный.
        logger.warning("Timepad HTTP %s — проверь TIMEPAD_TOKEN.", r.status_code)
        return []
    if r.status_code == 429:
        logger.warning("Timepad HTTP 429 (rate-limit) — пропускаем тик.")
        return []
    if r.status_code != 200:
        logger.warning("Timepad HTTP %s", r.status_code)
        return []

    try:
        payload = r.json()
    except Exception as e:
        logger.warning("Timepad JSON parse failed: %s", e)
        return []

    values = payload.get("values") or []
    out: list[dict] = []
    for item in values[:limit]:
        title = (item.get("name") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "raw_description": _build_raw_description(item),
            "source_url": item.get("url") or "",
        })
    return out
