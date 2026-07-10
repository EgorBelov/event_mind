"""Inline-клавиатуры бота. callback_data кодируем как `<action>:<event_id>`."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def feedback_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Кнопки под карточкой рекомендации: like / save / hide + подробнее."""
    kb = InlineKeyboardBuilder()
    kb.button(text="👍 Нравится", callback_data=f"like:{event_id}")
    kb.button(text="⭐ Сохранить", callback_data=f"save:{event_id}")
    kb.button(text="👎 Скрыть", callback_data=f"hide:{event_id}")
    kb.button(text="📖 Подробнее", callback_data=f"more:{event_id}")
    kb.adjust(3, 1)
    return kb.as_markup()


def more_keyboard(event_id: int, source_url: str | None) -> InlineKeyboardMarkup:
    """Кнопка «на источник» под карточкой события (если есть URL)."""
    rows: list[list[InlineKeyboardButton]] = []
    if source_url:
        rows.append([InlineKeyboardButton(text="🔗 На источнике", url=source_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
