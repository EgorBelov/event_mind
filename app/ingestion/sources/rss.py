"""Универсальный парсер RSS/Atom-лент через feedparser.

Принимает список URL и возвращает сырые события в том же формате, что и
`app.ingestion.sources.habr` — `{title, raw_description, source_url}`.
"""

import feedparser

from app.core.logging import get_logger

logger = get_logger(__name__)


def fetch_rss_events(feed_urls: list[str], limit_per_feed: int = 20) -> list[dict]:
    """Скачать события из набора RSS/Atom-лент.

    Поломанная или недоступная лента игнорируется — функция не падает целиком.
    Дубликаты по `link` отбрасываются между лентами в рамках одного вызова.
    """
    result: list[dict] = []
    seen: set[str] = set()

    for url in feed_urls:
        url = url.strip()
        if not url:
            continue
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "EventMind/1.0"})
        except Exception as e:
            logger.warning("RSS: failed to parse %s: %s", url, e)
            continue

        if feed.bozo and not feed.entries:
            logger.warning("RSS: bozo & empty feed at %s", url)
            continue

        added_from_feed = 0
        for entry in feed.entries:
            if added_from_feed >= limit_per_feed:
                break
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            if link in seen:
                continue
            seen.add(link)

            description = (
                entry.get("summary")
                or entry.get("description")
                or ""
            ).strip()
            published = (entry.get("published") or entry.get("updated") or "").strip()

            parts = [p for p in [published, description] if p]
            raw_description = " | ".join(parts) if parts else title

            result.append({
                "title": title,
                "raw_description": raw_description,
                "source_url": link,
            })
            added_from_feed += 1

    logger.info("RSS: fetched %d entries from %d feed(s)", len(result), len(feed_urls))
    return result
