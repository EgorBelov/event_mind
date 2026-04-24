from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOPIC_LABELS = {
    "ai_ml": "AI / ML",
    "data_science": "Data Science",
    "business_analytics": "Бизнес-аналитика",
    "backend": "Backend",
    "product": "Product",
}

FORMAT_LABELS = {
    "online": "Онлайн",
    "offline": "Оффлайн",
    "any": "Без разницы",
}

CITY_LABELS = {
    "moscow": "Москва",
    "spb": "Санкт-Петербург",
    "any": "Любой",
}


def start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать", callback_data="start_setup")
    builder.button(text="Как это работает", callback_data="how_it_works")
    builder.adjust(1)
    return builder.as_markup()


def topics_keyboard(selected_topics: set[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for topic_key, topic_label in TOPIC_LABELS.items():
        prefix = "✅ " if topic_key in selected_topics else ""
        builder.button(text=f"{prefix}{topic_label}", callback_data=f"topic:{topic_key}")

    builder.button(text="Готово", callback_data="topics_done")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def format_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for format_key, format_label in FORMAT_LABELS.items():
        builder.button(text=format_label, callback_data=f"format:{format_key}")

    builder.adjust(2, 1)
    return builder.as_markup()


def city_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for city_key, city_label in CITY_LABELS.items():
        builder.button(text=city_label, callback_data=f"city:{city_key}")

    builder.adjust(2, 1)
    return builder.as_markup()


def after_setup_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Показать рекомендации", callback_data="show_recommendations")
    builder.adjust(1)
    return builder.as_markup()


def recommendation_keyboard(
    event_id: int,
    actions: set[str] | None = None,
) -> InlineKeyboardMarkup:
    actions = actions or set()

    like_text = "✅ Интересно" if "like" in actions else "Интересно"
    dislike_text = "❌ Не интересно" if "dislike" in actions else "Не интересно"
    save_text = "⭐ Сохранено" if "save" in actions else "Сохранить"

    builder = InlineKeyboardBuilder()
    builder.button(text=like_text, callback_data=f"like:{event_id}")
    builder.button(text=dislike_text, callback_data=f"dislike:{event_id}")
    builder.button(text=save_text, callback_data=f"save:{event_id}")
    builder.button(text="Следующее", callback_data="next_recommendation")
    builder.adjust(2, 2)
    return builder.as_markup()

def ai_recommendation_keyboard(
    event_id: int,
    actions: set[str] | None = None,
) -> InlineKeyboardMarkup:
    actions = actions or set()

    like_text = "✅ Интересно" if "like" in actions else "Интересно"
    dislike_text = "❌ Не интересно" if "dislike" in actions else "Не интересно"
    save_text = "⭐ Сохранено" if "save" in actions else "Сохранить"

    builder = InlineKeyboardBuilder()
    builder.button(text=like_text, callback_data=f"ai_like:{event_id}")
    builder.button(text=dislike_text, callback_data=f"ai_dislike:{event_id}")
    builder.button(text=save_text, callback_data=f"ai_save:{event_id}")
    builder.button(text="Следующее AI", callback_data="next_ai_recommendation")
    builder.adjust(2, 2)
    return builder.as_markup()