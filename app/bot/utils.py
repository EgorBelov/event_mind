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

from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest


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
