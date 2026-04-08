from dataclasses import dataclass, field

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.inline import (
    start_keyboard,
    topics_keyboard,
    format_keyboard,
    city_keyboard,
    after_setup_keyboard,
    TOPIC_LABELS,
    FORMAT_LABELS,
    CITY_LABELS,
)
from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.reply import setup_keyboard, main_menu_keyboard

router = Router()
api_client = EventMindAPIClient()


@dataclass
class SetupState:
    topics: set[str] = field(default_factory=set)
    preferred_format: str | None = None
    city: str | None = None


user_setup_state: dict[int, SetupState] = {}


def get_state(user_id: int) -> SetupState:
    if user_id not in user_setup_state:
        user_setup_state[user_id] = SetupState()
    return user_setup_state[user_id]


@router.message(CommandStart())
async def cmd_start(message: Message):
    user_setup_state[message.from_user.id] = SetupState()

    await message.answer(
        "Привет! Я *EventMind* — бот для подбора IT-событий по твоим интересам.\n\n"
        "Я могу:\n"
        "- подобрать мероприятия по темам и формату;\n"
        "- показать наиболее подходящие события;\n"
        "- учитывать твои предпочтения для персональных рекомендаций.\n\n"
        "Давай быстро настроим профиль.",
        reply_markup=setup_keyboard(),
        parse_mode="Markdown",
    )

    await message.answer(
        "Также можно использовать inline-кнопки ниже:",
        reply_markup=start_keyboard(),
    )


@router.callback_query(F.data == "how_it_works")
async def cb_how_it_works(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Я подбираю IT-события на основе твоих интересов.\n\n"
        "Сначала ты указываешь темы, формат и город, а затем я показываю подходящие мероприятия.\n"
        "В дальнейшем рекомендации можно улучшать по твоим действиям."
    )


@router.callback_query(F.data == "start_setup")
async def cb_start_setup(callback: CallbackQuery):
    await callback.answer()
    state = get_state(callback.from_user.id)

    await callback.message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics),
    )


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic_toggle(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    topic_key = callback.data.split(":", 1)[1]

    if topic_key in state.topics:
        state.topics.remove(topic_key)
    else:
        state.topics.add(topic_key)

    await callback.message.edit_reply_markup(reply_markup=topics_keyboard(state.topics))


@router.callback_query(F.data == "topics_done")
async def cb_topics_done(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)

    if not state.topics:
        await callback.message.answer("Выбери хотя бы одну тему.")
        return

    selected_topics = ", ".join(TOPIC_LABELS[topic] for topic in state.topics)

    await callback.message.answer(
        f"Отлично. Я сохранил выбранные темы:\n{selected_topics}\n\n"
        f"Теперь выбери предпочитаемый формат событий.",
        reply_markup=format_keyboard(),
    )


@router.callback_query(F.data.startswith("format:"))
async def cb_format_selected(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    state.preferred_format = callback.data.split(":", 1)[1]

    await callback.message.answer(
        "Укажи город для оффлайн-событий.",
        reply_markup=city_keyboard(),
    )


@router.callback_query(F.data.startswith("city:"))
async def cb_city_selected(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    state.city = callback.data.split(":", 1)[1]

    user = callback.from_user

    await api_client.register_user(
        telegram_id=user.id,
        username=user.username,
        preferred_format=state.preferred_format,
        city=state.city,
        topics=list(state.topics),
    )

    topics_text = ", ".join(TOPIC_LABELS[topic] for topic in state.topics)
    format_text = FORMAT_LABELS.get(state.preferred_format, state.preferred_format)
    city_text = CITY_LABELS.get(state.city, state.city)

    await callback.message.answer(
        f"Профиль настроен.\n\n"
        f"Я учту:\n"
        f"- темы: {topics_text}\n"
        f"- формат: {format_text}\n"
        f"- город: {city_text}\n\n"
        f"Теперь можно посмотреть рекомендации.",
        reply_markup=after_setup_keyboard(),
    )

    await callback.message.answer(
        "Главное меню обновлено.",
        reply_markup=main_menu_keyboard(),
    )

@router.message(Command("edit"))
async def cmd_edit(message: Message):
    user_setup_state[message.from_user.id] = SetupState()

    await message.answer(
        "Давай обновим профиль.\n\n"
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(set()),
    )

@router.message(F.text == "Изменить профиль")
async def msg_edit_profile(message: Message):
    user_setup_state[message.from_user.id] = SetupState()

    await message.answer(
        "Давай обновим профиль.\n\n"
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(set()),
    )

@router.message(F.text == "Начать настройку")
async def msg_start_setup(message: Message):
    state = get_state(message.from_user.id)

    await message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics),
    )