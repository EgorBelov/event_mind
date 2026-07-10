"""Meetup — GraphQL API (требует Pro-аккаунт + OAuth-токен).

ВНИМАНИЕ: с конца 2024 публичный REST у Meetup закрыт; GraphQL доступен
только для Pro-Network подписчиков. Поэтому здесь — скелет с интерфейсом.

Чтобы включить:
1. Получить `meetup_access_token` (https://www.meetup.com/api/oauth/).
2. Передать через `.env`: `MEETUP_TOKEN=...`, `MEETUP_GROUPS=urlname1,urlname2`.
3. Реализовать `_query_graphql` под актуальную схему (changes часты).
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_GRAPHQL_URL = "https://api.meetup.com/gql"

_EVENTS_QUERY = """
query($urlname: String!) {
  groupByUrlname(urlname: $urlname) {
    upcomingEvents(input: {first: 20}) {
      edges {
        node {
          id
          title
          description
          eventUrl
          dateTime
          venue { city }
        }
      }
    }
  }
}
"""


def fetch_meetup_events(limit_per_group: int = 20) -> list[dict]:
    token = getattr(settings, "meetup_token", "") or ""
    groups_raw = getattr(settings, "meetup_groups", "") or ""
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
    if not token or not groups:
        logger.info("Meetup: MEETUP_TOKEN/MEETUP_GROUPS не заданы — источник пропущен.")
        return []

    out: list[dict] = []
    for urlname in groups:
        try:
            response = httpx.post(
                _GRAPHQL_URL,
                json={"query": _EVENTS_QUERY, "variables": {"urlname": urlname}},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
            if response.status_code != 200:
                logger.warning("Meetup HTTP %s for %s", response.status_code, urlname)
                continue
            data = response.json()
            edges = (data.get("data", {}) or {}).get("groupByUrlname", {}).get("upcomingEvents", {}).get("edges", [])
            for edge in edges[:limit_per_group]:
                node = edge.get("node") or {}
                title = node.get("title") or ""
                if not title:
                    continue
                city = (node.get("venue") or {}).get("city")
                desc = node.get("description") or ""
                if city:
                    desc += f"\n\nГород: {city}"
                if node.get("dateTime"):
                    desc += f"\nДата: {node['dateTime']}"
                out.append({
                    "title": title,
                    "raw_description": desc.strip(),
                    "source_url": node.get("eventUrl", ""),
                })
        except Exception as e:
            logger.warning("Meetup fetch failed for %s: %s", urlname, e)
    return out
