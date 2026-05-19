from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.topics import (
    SEED_TOPIC_TITLES,
    SEED_CITY_LABELS,
    city_label,
    format_label,
    topic_title,
)

# Seed-значения по умолчанию — отправная точка для мастера настройки.
# Реальные лукапы лучше делать через topic_title()/format_label()/city_label():
# они откатываются на humanize_code(), если код неизвестен (например, когда
# новый город/тема появились из спарсенных событий).
TOPIC_LABELS = dict(SEED_TOPIC_TITLES)
FORMAT_LABELS = {
    "online": "Онлайн",
    "offline": "Оффлайн",
    "hybrid": "Гибрид",
    "any": "Без разницы",
}
CITY_LABELS = {**SEED_CITY_LABELS, "any": "Любой"}


def _label_for_topic(code: str) -> str:
    return TOPIC_LABELS.get(code) or topic_title(code)


def _label_for_format(code: str) -> str:
    return FORMAT_LABELS.get(code) or format_label(code)


def _label_for_city(code: str) -> str:
    return CITY_LABELS.get(code) or city_label(code)


def start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать", callback_data="start_setup")
    builder.button(text="Как это работает", callback_data="how_it_works")
    builder.adjust(1)
    return builder.as_markup()


def topics_keyboard(
    selected_topics: set[str],
    extra_codes: list[str] | None = None,
) -> InlineKeyboardMarkup:
    """Собрать клавиатуру тем. `extra_codes` — динамические темы из БД."""
    builder = InlineKeyboardBuilder()

    # Сначала seed-темы в стабильном порядке; затем дополнения (без дубликатов)
    codes: list[str] = list(TOPIC_LABELS.keys())
    if extra_codes:
        for code in extra_codes:
            if code and code not in codes:
                codes.append(code)

    for code in codes:
        prefix = "✅ " if code in selected_topics else ""
        builder.button(text=f"{prefix}{_label_for_topic(code)}", callback_data=f"topic:{code}")

    builder.button(text="Готово", callback_data="topics_done")
    # Автогрид: по 2 кнопки в строке + финальная "Готово" отдельно
    rows = [2] * ((len(codes) + 1) // 2) + [1]
    builder.adjust(*rows)
    return builder.as_markup()


def format_keyboard(extra_codes: list[str] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    codes = list(FORMAT_LABELS.keys())
    if extra_codes:
        for c in extra_codes:
            if c and c not in codes:
                codes.append(c)
    for code in codes:
        builder.button(text=_label_for_format(code), callback_data=f"format:{code}")
    builder.adjust(2, 2)
    return builder.as_markup()


def city_keyboard(extra_codes: list[str] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    codes = list(CITY_LABELS.keys())
    if extra_codes:
        for c in extra_codes:
            if c and c not in codes:
                codes.append(c)
    for code in codes:
        builder.button(text=_label_for_city(code), callback_data=f"city:{code}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def after_setup_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Показать рекомендации", callback_data="show_recommendations")
    builder.adjust(1)
    return builder.as_markup()


def recommendation_keyboard(
    event_id: int,
    actions: set[str] | None = None,
    mode: str = "rule",
) -> InlineKeyboardMarkup:
    """Клавиатура карточки события.

    Единая для обычных и AI-рекомендаций: like/dislike/save идут в один и тот
    же эндпойнт, поэтому отличается только листание (`mode`: "rule" | "ai"),
    которое прокинуто в callback_data, чтобы перерисовка после реакции знала,
    какую кнопку «Следующее» рендерить.
    """
    actions = actions or set()

    like_text = "✅ Интересно" if "like" in actions else "Интересно"
    dislike_text = "❌ Не интересно" if "dislike" in actions else "Не интересно"
    save_text = "⭐ Сохранено" if "save" in actions else "Сохранить"
    next_text = "Следующее AI" if mode == "ai" else "Следующее"

    builder = InlineKeyboardBuilder()
    builder.button(text=like_text, callback_data=f"like:{mode}:{event_id}")
    builder.button(text=dislike_text, callback_data=f"dislike:{mode}:{event_id}")
    builder.button(text=save_text, callback_data=f"save:{mode}:{event_id}")
    builder.button(text="Похожие", callback_data=f"similar:{event_id}")
    builder.button(text=next_text, callback_data=f"next:{mode}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def recommendations_picker_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Обычные", callback_data="recs:rule")
    builder.button(text="🤖 AI", callback_data="recs:ai")
    builder.adjust(2)
    return builder.as_markup()


def profile_actions_keyboard(is_subscribed: bool) -> InlineKeyboardMarkup:
    digest_label = "📬 AI-дайджест: ВКЛ" if is_subscribed else "📭 AI-дайджест: ВЫКЛ"
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Избранное", callback_data="profile:saved")
    builder.button(text="📊 Активность", callback_data="profile:stats")
    builder.button(text="✏️ Изменить профиль", callback_data="profile:edit")
    builder.button(text=digest_label, callback_data="profile:toggle_digest")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def more_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Тренды", callback_data="more:trending")
    builder.button(text="🎯 Copilot", callback_data="more:copilot")
    builder.button(text="❓ Помощь", callback_data="more:help")
    builder.adjust(2, 1)
    return builder.as_markup()
