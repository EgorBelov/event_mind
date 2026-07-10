"""Надёжная отправка сообщений (HTML + plain-fallback).

Порт `send` из `legacy/app/bot/utils.py`: карточки/ответы содержат
произвольный текст со спарсенных сайтов; при отказе HTML-парсинга на стороне
Telegram повторяем plain-text, чтобы сообщение не «пропало».
"""
from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from eventmind.interfaces.bot.formatting import to_plain


async def send(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if isinstance(target, Message):
        answer = target.answer
    else:
        message = target.message
        if not isinstance(message, Message):
            return
        answer = message.answer
    try:
        await answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        await answer(to_plain(text), reply_markup=reply_markup)
