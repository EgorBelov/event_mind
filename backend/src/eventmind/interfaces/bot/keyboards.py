"""Inline-клавиатуры бота. callback_data — `<action>:<arg>` (≤ 64 байт).

| callback          | что делает                                        |
|-------------------|---------------------------------------------------|
| like/save/hide:ID | оценка события (лента, поиск, «Подробнее»)        |
| more:ID           | «📖 Подробнее» — пересказ + почему рекомендовано  |
| feed:more         | следующая порция ленты                            |
| fmt:X / city:X    | формат / город (онбординг и настройки; "" — не важно) |
| onb:skip          | пропустить «о себе» в онбординге                  |
| set:*             | пункты /settings                                  |
| unsave:ID         | убрать из сохранённого                            |
| saved:OFFSET      | следующая страница сохранённого                   |
| agent:yes/no:ID   | подтвердить / отклонить изменение, предложенное агентом |
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Популярные города для быстрого выбора; остальные — текстом («Другой»).
QUICK_CITIES: tuple[tuple[str, str], ...] = (
    ("moscow", "Москва"),
    ("spb", "Санкт-Петербург"),
    ("perm", "Пермь"),
    ("kazan", "Казань"),
    ("novosibirsk", "Новосибирск"),
    ("ekb", "Екатеринбург"),
    ("nizhny_novgorod", "Нижний Новгород"),
)

DIGEST_LABELS = {"daily": "ежедневно", "weekly": "еженедельно", "off": "выключен"}
DIGEST_NEXT = {"daily": "weekly", "weekly": "off", "off": "daily"}
QUIET_DEFAULT = (23, 8)  # тихие часы по умолчанию при включении


def feedback_keyboard(event_id: int, source_url: str | None = None) -> InlineKeyboardMarkup:
    """Под карточкой события (лента, поиск, «Подробнее»): оценки + подробнее + источник."""
    kb = InlineKeyboardBuilder()
    kb.button(text="👍 Нравится", callback_data=f"like:{event_id}")
    kb.button(text="⭐ Сохранить", callback_data=f"save:{event_id}")
    kb.button(text="👎 Скрыть", callback_data=f"hide:{event_id}")
    kb.button(text="📖 Подробнее", callback_data=f"more:{event_id}")
    if source_url:
        kb.button(text="🔗 На источнике", url=source_url)
        kb.adjust(3, 2)
    else:
        kb.adjust(3, 1)
    return kb.as_markup()


def more_keyboard(event_id: int, source_url: str | None) -> InlineKeyboardMarkup:
    """Совместимость: карточка с оценками (раньше — только ссылка на источник)."""
    return feedback_keyboard(event_id, source_url)


def feed_more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Ещё ▶", callback_data="feed:more")]]
    )


def skip_about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="onb:skip")]]
    )


def format_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💻 Онлайн", callback_data="fmt:online")
    kb.button(text="🏢 Офлайн", callback_data="fmt:offline")
    kb.button(text="🔀 Гибрид", callback_data="fmt:hybrid")
    kb.button(text="Не важно", callback_data="fmt:")
    kb.adjust(3, 1)
    return kb.as_markup()


def city_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for slug, label in QUICK_CITIES:
        kb.button(text=label, callback_data=f"city:{slug}")
    kb.button(text="✍️ Другой — напишу", callback_data="city:other")
    kb.button(text="Не важно", callback_data="city:")
    kb.adjust(2, 2, 2, 1, 2)
    return kb.as_markup()


def settings_keyboard(digest_frequency: str, quiet_on: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ О себе", callback_data="set:about")
    kb.button(text="📍 Город", callback_data="set:city")
    kb.button(text="💻 Формат", callback_data="set:fmt")
    kb.button(
        text=f"📬 Дайджест: {DIGEST_LABELS.get(digest_frequency, digest_frequency)}",
        callback_data="set:digest",
    )
    start, end = QUIET_DEFAULT
    kb.button(
        text="🔔 Выключить тихие часы" if quiet_on else f"🔕 Тихие часы {start}–{end:02d}",
        callback_data="set:quiet",
    )
    kb.button(text="⭐ Сохранённое", callback_data="set:saved")
    kb.adjust(3, 1, 1, 1)
    return kb.as_markup()


def saved_item_keyboard(event_id: int, source_url: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Убрать", callback_data=f"unsave:{event_id}")
    kb.button(text="📖 Подробнее", callback_data=f"more:{event_id}")
    if source_url:
        kb.button(text="🔗 На источнике", url=source_url)
    kb.adjust(2, 1)
    return kb.as_markup()


def saved_more_keyboard(next_offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ещё ▶", callback_data=f"saved:{next_offset}")]
        ]
    )


def agent_confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    """«Да / Нет» под изменением профиля или настроек, которое предложил агент."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"agent:yes:{action_id}"),
                InlineKeyboardButton(text="✖️ Нет", callback_data=f"agent:no:{action_id}"),
            ]
        ]
    )
