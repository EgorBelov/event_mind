"""KudaGo — открытый JSON API афиши событий.

Документация: https://kudago.com/public-api/
Используется endpoint `/public-api/v1.4/events/?categories=education,fashion,...`.
Фильтруем по IT-категориям и ключевым словам — финальная фильтрация
не-IT всё равно делает LLM-нормализатор.
"""
from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

API = "https://kudago.com/public-api/v1.4/events/"
# В KudaGo нет «IT» категории явно, поэтому берём пограничные и доверяем
# LLM-нормализатору отфильтровать non-IT.
_CATEGORIES = "concert,exhibition,education,festival"
_FIELDS = "id,title,short_title,description,site_url,categories,place,dates"


def fetch_kudago_events(limit: int = 20) -> list[dict]:
    """Скачать события из KudaGo. Возвращает [{title, raw_description, source_url}]."""
    try:
        response = httpx.get(
            API,
            params={
                "page_size": min(limit, 100),
                "categories": _CATEGORIES,
                "fields": _FIELDS,
                "expand": "place",
                "actual_since": int(__import__("time").time()),
            },
            timeout=15.0,
            headers={"User-Agent": "EventMind/1.0"},
        )
        if response.status_code != 200:
            logger.warning("KudaGo HTTP %s", response.status_code)
            return []
        items = response.json().get("results", [])
    except Exception as e:
        logger.warning("KudaGo fetch failed: %s", e)
        return []

    out: list[dict] = []
    for item in items[:limit]:
        title = item.get("title") or item.get("short_title") or ""
        descr = item.get("description") or ""
        url = item.get("site_url") or ""
        place = item.get("place") or {}
        city = place.get("city", {}).get("name") if isinstance(place, dict) else None
        # Собираем «сырое описание», которое нормализатор разберёт.
        raw = f"{descr}\n\nГород: {city or 'не указан'}"
        if title:
            out.append({"title": title.strip(), "raw_description": raw.strip(), "source_url": url})
    return out
