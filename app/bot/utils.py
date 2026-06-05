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
    рисуем как есть, но если это голый ISO «2026-06-16» — переводим
    в человеческий «16 июня 2026»).

    Важно: если источник не дал часы/минуты, `start_at` лежит как
    `00:00:00` UTC — после конвертации в MSK получилось бы «03:00»,
    что вводит в заблуждение. В таких случаях показываем только дату.
    """
    raw_iso = event.get("start_at")
    if raw_iso:
        try:
            dt = datetime.fromisoformat(raw_iso)
            # Запоминаем «было ли вообще время» ДО конвертации зоны:
            # 00:00 UTC после astimezone(MSK) превратится в 03:00 — это не
            # реальное время мероприятия, источник его просто не дал.
            time_known = bool(dt.hour or dt.minute or dt.second)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local = dt.astimezone(tz)
            month = _MONTHS_RU_GEN[local.month - 1]
            if time_known:
                return (
                    f"{local.day} {month} {local.year}, "
                    f"{local:%H:%M} {tz.key.split('/')[-1]}"
                )
            return f"{local.day} {month} {local.year}"
        except Exception:
            pass

    raw_date = (event.get("date") or "").strip()
    if not raw_date:
        return "—"
    # ISO-строка «2026-06-16» без времени → переводим в человеческий вид.
    try:
        d = datetime.fromisoformat(raw_date).date()
        return f"{d.day} {_MONTHS_RU_GEN[d.month - 1]} {d.year}"
    except ValueError:
        return raw_date


def esc(value) -> str:
    """Экранировать произвольное значение для HTML parse_mode Telegram."""
    return html.escape("" if value is None else str(value))


def event_url_line(event: dict, label: str = "🔗 Открыть на источнике") -> str:
    """HTML-строка со ссылкой на источник события, либо пустая.

    Возвращает либо `\\n<a href="...">label</a>`, либо `""`. URL экранируется
    как HTML-атрибут — Telegram строго парсит href и роняет всё сообщение
    при невалидной кавычке.
    """
    url = (event.get("source_url") or "").strip()
    if not url:
        return ""
    safe_url = html.escape(url, quote=True)
    return f'\n<a href="{safe_url}">{html.escape(label)}</a>'


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
