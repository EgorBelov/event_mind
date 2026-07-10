"""Источник Habr events (async HTML-парсинг). Порт из legacy/app/ingestion/sources/habr.py."""
from __future__ import annotations

import httpx
import structlog
from bs4 import BeautifulSoup, Tag

from eventmind.application.ports.sources import RawEventDraft

_logger = structlog.get_logger("eventmind.sources.habr")

_URL = "https://habr.com/ru/events/"
_BASE = "https://habr.com"
_HEADERS = {"User-Agent": "EventMind/2.0", "Accept": "text/html,application/xhtml+xml"}


def _text(tag: Tag, selector: str) -> str:
    el = tag.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""


def parse_habr_html(html: str, *, limit: int = 20) -> list[RawEventDraft]:
    """Чистый парсинг HTML страницы событий Habr в драфты (тестируется без сети)."""
    soup = BeautifulSoup(html, "lxml")
    drafts: list[RawEventDraft] = []
    seen: set[str] = set()
    for section in soup.select("section.tm-block"):
        title_tag = section.select_one(".tm-event-card__title-link")
        if not isinstance(title_tag, Tag):
            continue
        title = title_tag.get_text(" ", strip=True)
        href = str(title_tag.get("href") or "")
        if not title or not href:
            continue
        if href.startswith("/"):
            href = _BASE + href
        if href in seen:
            continue
        seen.add(href)

        parts = [
            p
            for p in (
                _text(section, ".tm-event-card__day"),
                _text(section, ".tm-event-card__places-list"),
                _text(section, ".tm-event-card__categories"),
            )
            if p
        ]
        drafts.append(
            RawEventDraft(
                title=title,
                raw_description=" | ".join(parts) if parts else title,
                source_url=href,
            )
        )
        if len(drafts) >= limit:
            break
    return drafts


class HabrSource:
    name = "habr"

    async def fetch(self, limit: int = 20) -> list[RawEventDraft]:
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
                resp = await client.get(_URL)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            _logger.warning("habr_fetch_failed", error=str(exc))
            return []
        try:
            drafts = parse_habr_html(html, limit=limit)
        except Exception as exc:
            _logger.warning("habr_parse_failed", error=str(exc))
            return []
        _logger.info("habr_fetched", count=len(drafts))
        return drafts
