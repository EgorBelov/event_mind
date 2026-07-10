"""Lu.ma — публичные ICS-фиды календарей.

Lu.ma не имеет открытого REST API, но каждый календарь экспортируется как
iCalendar (.ics). Список URL календарей задаётся переменной окружения
`LUMA_CALENDARS=https://api.lu.ma/ics/get?entity=cal-xxx,https://...`.

Парсинг — через `ics` (мини-библиотека) либо ручной regex над VEVENT.
Здесь — ручной, чтобы не плодить зависимости.
"""
from __future__ import annotations

import re

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_VEVENT_RE = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Z\-;=A-Z0-9]+):(.*)$", re.MULTILINE)


def _parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    for block in _VEVENT_RE.findall(text):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.split(";")[0].strip()
                fields[key] = val.strip()
        title = fields.get("SUMMARY")
        if not title:
            continue
        events.append({
            "title": title,
            "raw_description": fields.get("DESCRIPTION", "").replace("\\n", "\n"),
            "source_url": fields.get("URL", ""),
            "starts_at": fields.get("DTSTART", ""),
            "location": fields.get("LOCATION", ""),
        })
    return events


def fetch_luma_events(limit_per_calendar: int = 20) -> list[dict]:
    """Скачать события со всех Lu.ma-календарей из env LUMA_CALENDARS."""
    urls_raw = getattr(settings, "luma_calendars", "") or ""
    urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
    if not urls:
        return []

    out: list[dict] = []
    for url in urls:
        try:
            response = httpx.get(url, timeout=15.0, headers={"User-Agent": "EventMind/1.0"})
            if response.status_code != 200:
                logger.warning("Lu.ma HTTP %s for %s", response.status_code, url)
                continue
            for ev in _parse_ics(response.text)[:limit_per_calendar]:
                desc = ev["raw_description"]
                if ev.get("location"):
                    desc += f"\n\nМесто: {ev['location']}"
                if ev.get("starts_at"):
                    desc += f"\nНачало: {ev['starts_at']}"
                out.append({
                    "title": ev["title"],
                    "raw_description": desc.strip(),
                    "source_url": ev.get("source_url") or url,
                })
        except Exception as e:
            logger.warning("Lu.ma fetch failed for %s: %s", url, e)
            continue
    return out
