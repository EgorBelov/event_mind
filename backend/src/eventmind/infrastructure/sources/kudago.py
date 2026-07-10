"""KudaGo — открытый JSON-API афиши (async). Порт из legacy kudago.py.

Берём пограничные категории и доверяем LLM-нормализатору отфильтровать не-IT.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from eventmind.application.ports.sources import RawEventDraft

_logger = structlog.get_logger("eventmind.sources.kudago")

_API = "https://kudago.com/public-api/v1.4/events/"
_CATEGORIES = "concert,exhibition,education,festival"
_FIELDS = "id,title,short_title,description,site_url,categories,place,dates"


def parse_kudago_items(items: list[dict[str, Any]], *, limit: int = 20) -> list[RawEventDraft]:
    """Чистый парсинг JSON-результатов KudaGo в драфты (тестируется без сети)."""
    drafts: list[RawEventDraft] = []
    for item in items[:limit]:
        title = (item.get("title") or item.get("short_title") or "").strip()
        if not title:
            continue
        descr = item.get("description") or ""
        place = item.get("place") or {}
        city = place.get("city", {}).get("name") if isinstance(place, dict) else None
        raw = f"{descr}\n\nГород: {city or 'не указан'}".strip()
        drafts.append(
            RawEventDraft(
                title=title, raw_description=raw, source_url=item.get("site_url") or None
            )
        )
    return drafts


class KudaGoSource:
    name = "kudago"

    async def fetch(self, limit: int = 20) -> list[RawEventDraft]:
        try:
            async with httpx.AsyncClient(
                timeout=15.0, headers={"User-Agent": "EventMind/2.0"}
            ) as client:
                resp = await client.get(
                    _API,
                    params={
                        "page_size": min(limit, 100),
                        "categories": _CATEGORIES,
                        "fields": _FIELDS,
                        "expand": "place",
                        "actual_since": int(time.time()),
                    },
                )
            if resp.status_code != 200:
                _logger.warning("kudago_http", status=resp.status_code)
                return []
            items = resp.json().get("results", [])
        except Exception as exc:
            _logger.warning("kudago_fetch_failed", error=str(exc))
            return []

        drafts = parse_kudago_items(items, limit=limit)
        _logger.info("kudago_fetched", count=len(drafts))
        return drafts
