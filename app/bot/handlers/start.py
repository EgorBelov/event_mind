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
from app.bot.utils import send

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

    await send(
        message,
        "Привет! Я <b>EventMind</b> — бот для подбора IT-событий по твоим интересам.\n\n"
        "Я могу:\n"
        "- подобрать мероприятия по темам и формату;\n"
        "- показать наиболее подходящие события;\n"
        "- учитывать твои предпочтения для персональных рекомендаций.\n\n"
        "Давай быстро настроим профиль.",
        reply_markup=setup_keyboard(),
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


async def _extra_topic_codes() -> list[str]:
    """Коды, которые есть в БД, но отсутствуют в seed-списке."""
    items = await api_client.get_vocabulary("topics")
    seed = set(TOPIC_LABELS.keys())
    return [item["code"] for item in items if item.get("code") and item["code"] not in seed]


async def _extra_city_codes() -> list[str]:
    items = await api_client.get_vocabulary("cities")
    from app.bot.keyboards.inline import CITY_LABELS as _seed_cities
    seed = set(_seed_cities.keys())
    return [item["code"] for item in items if item.get("code") and item["code"] not in seed]


@router.callback_query(F.data == "start_setup")
async def cb_start_setup(callback: CallbackQuery):
    await callback.answer()
    state = get_state(callback.from_user.id)

    await callback.message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes()),
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

    await callback.message.edit_reply_markup(
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes())
    )


@router.callback_query(F.data == "topics_done")
async def cb_topics_done(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)

    if not state.topics:
        await callback.message.answer("Выбери хотя бы одну тему.")
        return

    from app.core.topics import topic_title
    selected_topics = ", ".join(
        TOPIC_LABELS.get(topic) or topic_title(topic) for topic in state.topics
    )

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
        reply_markup=city_keyboard(extra_codes=await _extra_city_codes()),
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

    from app.core.topics import topic_title, format_label, city_label
    topics_text = ", ".join(
        TOPIC_LABELS.get(topic) or topic_title(topic) for topic in state.topics
    )
    format_text = FORMAT_LABELS.get(state.preferred_format) or format_label(state.preferred_format)
    city_text = CITY_LABELS.get(state.city) or city_label(state.city)

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
        reply_markup=topics_keyboard(set(), extra_codes=await _extra_topic_codes()),
    )

@router.callback_query(F.data == "profile:edit")
async def cb_profile_edit(callback: CallbackQuery):
    await callback.answer()
    user_setup_state[callback.from_user.id] = SetupState()

    await callback.message.answer(
        "Давай обновим профиль.\n\n"
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(set(), extra_codes=await _extra_topic_codes()),
    )


@router.message(F.text == "Начать настройку")
async def msg_start_setup(message: Message):
    state = get_state(message.from_user.id)

    await message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes()),
    )