"""Универсальный RSS/Atom-источник (feedparser в потоке). Порт из legacy rss.py."""
from __future__ import annotations

import asyncio
import ssl
import urllib.request
from typing import Any

import feedparser
import structlog

from eventmind.application.ports.sources import RawEventDraft

_logger = structlog.get_logger("eventmind.sources.rss")


def _ssl_handlers() -> list[Any]:
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        return [urllib.request.HTTPSHandler(context=ctx)]
    except Exception as exc:
        _logger.warning("rss_ca_bundle_unavailable", error=str(exc))
        return []


_HANDLERS = _ssl_handlers()


class RssSource:
    """Один источник поверх набора RSS/Atom-лент (feed_urls)."""

    def __init__(self, feed_urls: list[str], *, name: str = "rss") -> None:
        self._name = name
        self._feed_urls = feed_urls

    @property
    def name(self) -> str:
        return self._name

    async def fetch(self, limit: int = 20) -> list[RawEventDraft]:
        # feedparser синхронный и блокирующий → уводим в поток.
        return await asyncio.to_thread(self._fetch_sync, limit)

    def _fetch_sync(self, limit: int) -> list[RawEventDraft]:
        drafts: list[RawEventDraft] = []
        seen: set[str] = set()
        per_feed = max(1, limit // max(1, len(self._feed_urls)))
        for url in self._feed_urls:
            url = url.strip()
            if not url:
                continue
            try:
                feed = feedparser.parse(
                    url,
                    request_headers={"User-Agent": "EventMind/2.0"},
                    handlers=_HANDLERS,
                )
            except Exception as exc:
                _logger.warning("rss_feed_failed", url=url, error=str(exc))
                continue
            if feed.bozo and not feed.entries:
                continue

            added = 0
            for entry in feed.entries:
                if added >= per_feed or len(drafts) >= limit:
                    break
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                description = (entry.get("summary") or entry.get("description") or "").strip()
                published = (entry.get("published") or entry.get("updated") or "").strip()
                parts = [p for p in (published, description) if p]
                drafts.append(
                    RawEventDraft(
                        title=title,
                        raw_description=" | ".join(parts) if parts else title,
                        source_url=link,
                    )
                )
                added += 1
        _logger.info("rss_fetched", count=len(drafts), feeds=len(self._feed_urls))
        return drafts
