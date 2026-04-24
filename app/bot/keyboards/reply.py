from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Рекомендации"),
                KeyboardButton(text="AI-рекомендации"),
            ],
            [
                KeyboardButton(text="Профиль"),
                KeyboardButton(text="Избранное"),
            ],
            [
                KeyboardButton(text="Подписаться на AI"),
                KeyboardButton(text="Отписаться"),
            ],
            [
                KeyboardButton(text="Изменить профиль"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def setup_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Начать настройку")],
            [KeyboardButton(text="Как это работает")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )