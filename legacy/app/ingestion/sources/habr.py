"""Парсер страницы событий Habr для загрузки сырых событий в систему."""

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger

logger = get_logger(__name__)

HABR_EVENTS_URL = "https://habr.com/ru/events/"
_BASE = "https://habr.com"


def fetch_habr_events(limit: int = 20) -> list[dict]:
    """Скачать события с habr.com/ru/events/ через HTML-парсинг.

    Возвращает список словарей с ключами: title, raw_description, source_url.
    Любая сетевая или парсинговая ошибка → пустой список.
    """
    try:
        response = httpx.get(
            HABR_EVENTS_URL,
            timeout=10.0,
            headers={
                "User-Agent": "EventMind/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()
    except Exception as e:
        logger.warning("Habr: network error: %s", e)
        return []

    try:
        soup = BeautifulSoup(response.text, "lxml")
        sections = soup.select("section.tm-block")

        result: list[dict] = []
        seen: set[str] = set()

        for section in sections:
            title_tag = section.select_one(".tm-event-card__title-link")
            if not title_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            if not title:
                continue

            href = title_tag.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = _BASE + href

            if href in seen:
                continue
            seen.add(href)

            date = _text(section, ".tm-event-card__day")
            city = _text(section, ".tm-event-card__places-list")
            category = _text(section, ".tm-event-card__categories")

            parts = [p for p in [date, city, category] if p]
            raw_description = " | ".join(parts) if parts else title

            result.append({
                "title": title,
                "raw_description": raw_description,
                "source_url": href,
            })

            if len(result) >= limit:
                break

        logger.info("Habr: fetched %d events", len(result))
        return result

    except Exception as e:
        logger.error("Habr: parse error: %s", e)
        return []


def _text(tag, selector: str) -> str:
    el = tag.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""
