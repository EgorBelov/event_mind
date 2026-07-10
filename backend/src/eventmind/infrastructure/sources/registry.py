"""Реестр источников: собирает включённые `EventSource` из настроек."""
from __future__ import annotations

from eventmind.application.ports.sources import EventSource
from eventmind.config import Settings
from eventmind.infrastructure.sources.habr import HabrSource
from eventmind.infrastructure.sources.kudago import KudaGoSource
from eventmind.infrastructure.sources.rss import RssSource


def build_source_registry(settings: Settings) -> dict[str, EventSource]:
    """Собрать словарь {name: EventSource}. RSS включается, если заданы ленты."""
    registry: dict[str, EventSource] = {
        "habr": HabrSource(),
        "kudago": KudaGoSource(),
    }
    feeds = [u.strip() for u in settings.rss_feeds.split(",") if u.strip()]
    if feeds:
        registry["rss"] = RssSource(feeds)
    return registry
