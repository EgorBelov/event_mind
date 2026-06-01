"""Общие хелперы бота: безопасная отправка сообщений.

Карточки, списки и ответы LLM содержат произвольный текст со спарсенных
сайтов и от модели. С `parse_mode="Markdown"` несбалансированные
`*` `_` `[` `` ` `` ломали парсер Telegram — всё сообщение отвергалось
(TelegramBadRequest), и контент «пропадал». Здесь вся динамика экранируется
в HTML, а на любой сбой парсинга есть откат в plain-text, чтобы сообщение
не исчезало никогда.
"""
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

# Дефолтная таймзона рендеринга дат в боте. Можно сделать per-user (хранить
# users.timezone), но пока ~100% аудитории — Москва.
_DEFAULT_TZ = ZoneInfo("Europe/Moscow")
_MONTHS_RU_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_event_date(event: dict, tz: ZoneInfo = _DEFAULT_TZ) -> str:
    """Дата события для отображения в карточке.

    Приоритет — `start_at` (валидный DateTime от нормализатора): рендерим
    с локализацией в таймзону пользователя («1 июня 2026, 19:00 MSK»).
    Если `start_at` нет — fallback на строку `event["date"]` (то, что
    показывает источник; может быть «лето 2026», диапазон, и т.п. —
    рисуем как есть).
    """
    raw_iso = event.get("start_at")
    if raw_iso:
        try:
            dt = datetime.fromisoformat(raw_iso)
            # start_at из БД — naive UTC. Привязываем UTC, потом конвертируем.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local = dt.astimezone(tz)
            month = _MONTHS_RU_GEN[local.month - 1]
            time_part = f", {local:%H:%M}" if (local.hour or local.minute) else ""
            return f"{local.day} {month} {local.year}{time_part} {tz.key.split('/')[-1]}"
        except Exception:
            pass
    return event.get("date") or "—"


def esc(value) -> str:
    """Экранировать произвольное значение для HTML parse_mode Telegram."""
    return html.escape("" if value is None else str(value))


def to_plain(text: str) -> str:
    """HTML → plain: снять теги и развернуть сущности (для fallback)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def send(target: Message | CallbackQuery, text: str, reply_markup=None):
    """Ответить и для Message, и для CallbackQuery, надёжно отрисовав текст.

    Шлёт HTML; при отказе парсинга на стороне Telegram повторяет тем же
    адресатом без разметки, чтобы карточка/список не пропали.
    """
    answer = target.answer if isinstance(target, Message) else target.message.answer
    try:
        await answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        await answer(to_plain(text), reply_markup=reply_markup)
