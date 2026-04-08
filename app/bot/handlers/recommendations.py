from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.inline import recommendation_keyboard
from app.bot.services.api_client import EventMindAPIClient

router = Router()
api_client = EventMindAPIClient()

user_recommendation_index: dict[int, int] = {}


def format_event_card(event: dict) -> str:
    topics = ", ".join(event.get("topics", []))

    return (
        f"*{event['title']}*\n\n"
        f"Тема: {topics}\n"
        f"Формат: {event['format']}\n"
        f"Город: {event['city']}\n"
        f"Уровень: {event['level']}\n"
        f"Дата: {event['date']}\n\n"
        f"{event['description']}\n\n"
        f"{event['explanation']}\n"
        f"Score: {event['score']}"
    )


async def send_recommendation(target: Message | CallbackQuery, telegram_id: int):
    recommendations = await api_client.get_recommendations(telegram_id)

    if not recommendations:
        text = (
            "Пока нет рекомендаций.\n\n"
            "Сначала настрой профиль через /start "
            "или убедись, что пользователь зарегистрирован."
        )
        if isinstance(target, Message):
            await target.answer(text)
        else:
            await target.message.answer(text)
        return

    current_index = user_recommendation_index.get(telegram_id, 0)

    if current_index >= len(recommendations):
        user_recommendation_index[telegram_id] = 0
        end_text = (
            "Это все рекомендации по текущему профилю.\n\n"
            "Можешь снова вызвать /recommend."
        )
        if isinstance(target, Message):
            await target.answer(end_text)
        else:
            await target.message.answer(end_text)
        return

    event = recommendations[current_index]
    interactions_data = await api_client.get_event_interactions(telegram_id, event["event_id"])
    actions = set(interactions_data.get("actions", []))

    text = format_event_card(event)

    if isinstance(target, Message):
        await target.answer(
            text,
            reply_markup=recommendation_keyboard(event["event_id"], actions),
            parse_mode="Markdown",
        )
    else:
        await target.message.answer(
            text,
            reply_markup=recommendation_keyboard(event["event_id"], actions),
            parse_mode="Markdown",
        )


async def update_current_message_markup(callback: CallbackQuery, event_id: int):
    interactions_data = await api_client.get_event_interactions(callback.from_user.id, event_id)
    actions = set(interactions_data.get("actions", []))

    await callback.message.edit_reply_markup(
        reply_markup=recommendation_keyboard(event_id, actions)
    )


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    user_recommendation_index[message.from_user.id] = 0
    await send_recommendation(message, message.from_user.id)


@router.callback_query(F.data == "show_recommendations")
async def cb_show_recommendations(callback: CallbackQuery):
    await callback.answer()
    user_recommendation_index[callback.from_user.id] = 0
    await send_recommendation(callback, callback.from_user.id)


@router.callback_query(F.data == "next_recommendation")
async def cb_next_recommendation(callback: CallbackQuery):
    await callback.answer("Показываю следующее событие")
    user_id = callback.from_user.id
    user_recommendation_index[user_id] = user_recommendation_index.get(user_id, 0) + 1
    await send_recommendation(callback, user_id)


@router.callback_query(F.data.startswith("like:"))
async def cb_like(callback: CallbackQuery):
    event_id = int(callback.data.split(":", 1)[1])

    await api_client.save_interaction(
        telegram_id=callback.from_user.id,
        event_id=event_id,
        action="like",
    )
    await callback.answer("Отмечено как интересное")
    await update_current_message_markup(callback, event_id)


@router.callback_query(F.data.startswith("dislike:"))
async def cb_dislike(callback: CallbackQuery):
    event_id = int(callback.data.split(":", 1)[1])

    await api_client.save_interaction(
        telegram_id=callback.from_user.id,
        event_id=event_id,
        action="dislike",
    )
    await callback.answer("Отмечено как неинтересное")
    await update_current_message_markup(callback, event_id)


@router.callback_query(F.data.startswith("save:"))
async def cb_save(callback: CallbackQuery):
    event_id = int(callback.data.split(":", 1)[1])

    await api_client.save_interaction(
        telegram_id=callback.from_user.id,
        event_id=event_id,
        action="save",
    )
    await callback.answer("Событие сохранено")
    await update_current_message_markup(callback, event_id)