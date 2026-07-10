"""Чистые хелперы рендеринга карточек для бота (без aiogram — тестируемо).

Портирует локализацию дат и ссылку на источник из `legacy/app/bot/utils.py`,
но работает с dict'ами, которые бот получает от API (`EventDetailResponse`/
`RecommendationResponse`).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_DEFAULT_TZ = ZoneInfo("Europe/Moscow")
_MONTHS_RU_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def esc(value: Any) -> str:
    """Экранировать произвольное значение под HTML parse_mode Telegram."""
    return html.escape("" if value is None else str(value))


def to_plain(text: str) -> str:
    """HTML → plain: снять теги и развернуть сущности (для fallback)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def format_event_date(event: dict[str, Any], tz: ZoneInfo = _DEFAULT_TZ) -> str:
    """Дата события для карточки.

    Приоритет — `start_at` (ISO от нормализатора) с локализацией в TZ. Если
    время нулевое (источник его не дал — 00:00 UTC), показываем только дату,
    чтобы не выдумывать «03:00 MSK». Иначе — `date` как есть, а голый ISO
    переводим в человеческий вид.
    """
    raw_iso = event.get("start_at")
    if raw_iso:
        try:
            dt = datetime.fromisoformat(str(raw_iso))
            time_known = bool(dt.hour or dt.minute or dt.second)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local = dt.astimezone(tz)
            month = _MONTHS_RU_GEN[local.month - 1]
            if time_known:
                return f"{local.day} {month} {local.year}, {local:%H:%M} {tz.key.split('/')[-1]}"
            return f"{local.day} {month} {local.year}"
        except (ValueError, TypeError):
            pass

    raw_date = str(event.get("date") or "").strip()
    if not raw_date:
        return "—"
    try:
        d = datetime.fromisoformat(raw_date).date()
        return f"{d.day} {_MONTHS_RU_GEN[d.month - 1]} {d.year}"
    except ValueError:
        return raw_date


def event_url_line(event: dict[str, Any], label: str = "🔗 Открыть на источнике") -> str:
    """HTML-строка со ссылкой на источник, либо пустая. href экранируется."""
    url = str(event.get("source_url") or "").strip()
    if not url:
        return ""
    return f'\n<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


def render_event_card(event: dict[str, Any], *, score: float | None = None) -> str:
    """Собрать HTML-карточку события для сообщения бота."""
    lines = [f"<b>{esc(event.get('title'))}</b>"]
    meta: list[str] = [f"📅 {esc(format_event_date(event))}"]
    if event.get("city"):
        meta.append(f"📍 {esc(event['city'])}")
    if event.get("format"):
        meta.append(f"💻 {esc(event['format'])}")
    if event.get("event_type"):
        meta.append(f"🏷 {esc(event['event_type'])}")
    lines.append(" · ".join(meta))

    summary = str(event.get("summary") or event.get("description") or "").strip()
    if summary:
        clipped = summary[:400] + ("…" if len(summary) > 400 else "")
        lines.append(esc(clipped))

    topics = event.get("topics") or []
    if isinstance(topics, list) and topics:
        lines.append(" ".join(f"#{esc(t)}" for t in topics[:6]))

    line = event_url_line(event)
    card = "\n".join(lines)
    if score is not None:
        card += f"\n<i>★ {score:.2f}</i>"
    return card + line
