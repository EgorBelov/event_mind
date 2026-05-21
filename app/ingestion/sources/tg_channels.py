"""Telegram-каналы — скрапинг публичного web-preview `t.me/s/{channel}`.

Telegram отдаёт публичный HTML-предпросмотр канала по URL
`https://t.me/s/{channel_username}` — БЕЗ авторизации, без api_id/api_hash,
без telethon-userbot'а. Это самый надёжный путь чтения публичных каналов:
работает синхронно через httpx + BeautifulSoup, как наш Habr-парсер.

Каналы задаются в `.env`:
    TG_INGEST_CHANNELS=iteventsru,ITMeeting

Каналы, у которых владелец отключил web-preview (через @BotFather или
настройки), просто отдают страницу без сообщений — для них функция
вернёт пустой список и предупреждение в логах.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_BASE = "https://t.me/s/{channel}"
_POST_URL = "https://t.me/{channel}/{msg_id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}
_MIN_TEXT_LEN = 50          # короче — почти всегда репост/служебка
_MAX_TITLE_LEN = 200
_TITLE_TRIM_CHARS = " .—-:!?\t\n«»\"'`"


def _extract_message_text(node) -> str:
    """Достать текст одного <div class='tgme_widget_message_text'> с переносами."""
    if node is None:
        return ""
    # `<br>` → "\n", остальное соберём через .get_text()
    for br in node.find_all("br"):
        br.replace_with("\n")
    text = node.get_text(separator="", strip=False)
    # Сжимаем лишние пробелы в начале/конце строк, но сохраняем переносы
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


def _derive_title(text: str) -> str:
    """Первая значащая строка как заголовок (обрезанная)."""
    for raw_line in text.splitlines():
        line = raw_line.strip(_TITLE_TRIM_CHARS)
        # Пропускаем пустые и совсем короткие "буллет-эмодзи" префиксы
        if len(line) < 6:
            continue
        return line[:_MAX_TITLE_LEN].strip(_TITLE_TRIM_CHARS)
    # Fallback — обрезанный весь текст
    return text[:_MAX_TITLE_LEN].strip(_TITLE_TRIM_CHARS)


_POST_DATA_RE = re.compile(r"^([^/]+)/(\d+)$")


def _parse_channel_html(channel: str, html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict[str, Any]] = []
    for msg in soup.select("div.tgme_widget_message"):
        text_node = msg.select_one("div.tgme_widget_message_text")
        text = _extract_message_text(text_node)
        if len(text) < _MIN_TEXT_LEN:
            continue

        # Ссылка на пост — из data-post="{channel}/{msg_id}" или date-anchor.
        post_url = ""
        data_post = msg.get("data-post") or ""
        m = _POST_DATA_RE.match(data_post)
        if m:
            post_url = _POST_URL.format(channel=m.group(1), msg_id=m.group(2))
        else:
            date_a = msg.select_one("a.tgme_widget_message_date[href]")
            if date_a and date_a.get("href"):
                post_url = date_a["href"]

        # Дата (для будущего фильтра/сортировки)
        time_node = msg.select_one("a.tgme_widget_message_date time[datetime]")
        posted_at = time_node["datetime"] if time_node else ""

        title = _derive_title(text)
        if not title:
            continue

        # В raw_description оставляем и текст, и метку источника, и время —
        # LLM-нормализатор использует это для определения даты события.
        desc_lines = [text]
        if posted_at:
            desc_lines.append(f"\n[Опубликовано: {posted_at}]")
        desc_lines.append(f"\n[Источник: Telegram-канал @{channel}]")
        raw_description = "\n".join(desc_lines).strip()

        items.append({
            "title": title,
            "raw_description": raw_description,
            "source_url": post_url or f"https://t.me/{channel}",
        })
    return items


def _fetch_channel(channel: str) -> str | None:
    url = _BASE.format(channel=channel)
    try:
        response = httpx.get(url, timeout=15.0, headers=_HEADERS, follow_redirects=True)
    except Exception as e:
        logger.warning("TG: fetch %s failed: %s", channel, e)
        return None
    if response.status_code != 200:
        logger.warning("TG: %s HTTP %s", channel, response.status_code)
        return None
    return response.text


def fetch_telegram_events(limit_per_channel: int = 20) -> list[dict[str, Any]]:
    """Скачать события из всех Telegram-каналов в `settings.tg_ingest_channels`.

    Канал указывается как username без `@` или с `@` (мы нормализуем).
    Возвращает список {title, raw_description, source_url}.
    """
    channels_raw = getattr(settings, "tg_ingest_channels", "") or ""
    channels = [c.strip().lstrip("@") for c in channels_raw.split(",") if c.strip()]
    if not channels:
        logger.info("TG: TG_INGEST_CHANNELS не задан — источник пропущен.")
        return []

    out: list[dict[str, Any]] = []
    for channel in channels:
        html = _fetch_channel(channel)
        if not html:
            continue
        items = _parse_channel_html(channel, html)
        if not items:
            logger.info(
                "TG: канал @%s не содержит видимых сообщений (web-preview "
                "может быть отключён владельцем).",
                channel,
            )
            continue
        out.extend(items[:limit_per_channel])
    return out
