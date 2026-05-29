from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎯 Рекомендации"),
                KeyboardButton(text="🔍 Поиск"),
            ],
            [
                KeyboardButton(text="👤 Профиль"),
                KeyboardButton(text="⚙️ Ещё"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )
