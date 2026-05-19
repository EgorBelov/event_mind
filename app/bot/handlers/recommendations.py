from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.inline import (
    recommendation_keyboard,
    recommendations_picker_keyboard,
)
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, send

router = Router()
api_client = EventMindAPIClient()

user_recommendation_index: dict[int, int] = {}
user_ai_recommendation_index: dict[int, int] = {}
user_ai_recommendation_cards: dict[int, list[dict]] = {}


def format_event_card(event: dict) -> str:
    topics = ", ".join(event.get("topics", []))

    return (
        f"<b>{esc(event['title'])}</b>\n\n"
        f"Тема: {esc(topics)}\n"
        f"Формат: {esc(event['format'])}\n"
        f"Город: {esc(event['city'])}\n"
        f"Уровень: {esc(event['level'])}\n"
        f"Дата: {esc(event['date'])}\n\n"
        f"{esc(event['description'])}\n\n"
        f"{esc(event['explanation'])}\n"
        f"Score: {esc(event['score'])}"
    )


async def send_recommendation(target: Message | CallbackQuery, telegram_id: int):
    recommendations = await api_client.get_recommendations(telegram_id)

    if not recommendations:
        await send(
            target,
            "Пока нет рекомендаций.\n\n"
            "Сначала настрой профиль через /start "
            "или убедись, что пользователь зарегистрирован.",
        )
        return

    current_index = user_recommendation_index.get(telegram_id, 0)

    if current_index >= len(recommendations):
        user_recommendation_index[telegram_id] = 0
        await send(
            target,
            "Это все рекомендации по текущему профилю.\n\n"
            "Можешь снова вызвать /recommend.",
        )
        return

    event = recommendations[current_index]
    interactions_data = await api_client.get_event_interactions(telegram_id, event["event_id"])
    actions = set(interactions_data.get("actions", []))

    await send(
        target,
        format_event_card(event),
        reply_markup=recommendation_keyboard(event["event_id"], actions, mode="rule"),
    )


async def update_markup(callback: CallbackQuery, event_id: int, mode: str):
    """Перерисовать клавиатуру карточки, сохранив режим листания (rule/ai)."""
    interactions_data = await api_client.get_event_interactions(callback.from_user.id, event_id)
    actions = set(interactions_data.get("actions", []))

    await callback.message.edit_reply_markup(
        reply_markup=recommendation_keyboard(event_id, actions, mode=mode)
    )


def _parse_action_cb(data: str) -> tuple[str, int]:
    """`like:rule:123` -> ("rule", 123)."""
    _, mode, event_id = data.split(":", 2)
    return mode, int(event_id)


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    user_recommendation_index[message.from_user.id] = 0
    await send_recommendation(message, message.from_user.id)


@router.callback_query(F.data == "show_recommendations")
async def cb_show_recommendations(callback: CallbackQuery):
    await callback.answer()
    user_recommendation_index[callback.from_user.id] = 0
    await send_recommendation(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("next:"))
async def cb_next(callback: CallbackQuery):
    mode = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if mode == "ai":
        await callback.answer("Показываю следующую AI-рекомендацию")
        user_ai_recommendation_index[user_id] = user_ai_recommendation_index.get(user_id, 0) + 1
        await send_ai_recommendation_card(callback, user_id)
    else:
        await callback.answer("Показываю следующее событие")
        user_recommendation_index[user_id] = user_recommendation_index.get(user_id, 0) + 1
        await send_recommendation(callback, user_id)


@router.callback_query(F.data.startswith("like:"))
async def cb_like(callback: CallbackQuery):
    mode, event_id = _parse_action_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="like"
    )
    await callback.answer("Отмечено как интересное")
    await update_markup(callback, event_id, mode)


@router.callback_query(F.data.startswith("dislike:"))
async def cb_dislike(callback: CallbackQuery):
    mode, event_id = _parse_action_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="dislike"
    )
    await callback.answer("Отмечено как неинтересное")
    await update_markup(callback, event_id, mode)


@router.callback_query(F.data.startswith("save:"))
async def cb_save(callback: CallbackQuery):
    mode, event_id = _parse_action_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="save"
    )
    await callback.answer("Событие сохранено")
    await update_markup(callback, event_id, mode)


@router.callback_query(F.data.startswith("similar:"))
async def cb_similar(callback: CallbackQuery):
    """Показать события, похожие по темам (раньше кнопка была мёртвой)."""
    await callback.answer("Ищу похожие события")
    event_id = int(callback.data.split(":", 1)[1])
    similar = await api_client.get_similar_events(event_id, limit=3)

    if not similar:
        await callback.message.answer("Похожих событий не нашлось.")
        return

    lines = ["<b>Похожие события:</b>\n"]
    for e in similar:
        topics = ", ".join(e.get("topics", []))
        block = (
            f"<b>{esc(e['title'])}</b>\n"
            f"Тема: {esc(topics)}\n"
            f"Формат: {esc(e['format'])} · Город: {esc(e['city'])} · "
            f"Дата: {esc(e['date'])}"
        )
        if e.get("source_url"):
            block += f"\n{esc(e['source_url'])}"
        lines.append(block)

    await send(callback, "\n\n".join(lines))

@router.message(F.text == "🎯 Рекомендации")
async def msg_recommendations_picker(message: Message):
    await message.answer(
        "Какой вид рекомендаций показать?",
        reply_markup=recommendations_picker_keyboard(),
    )


@router.callback_query(F.data == "recs:rule")
async def cb_recs_rule(callback: CallbackQuery):
    await callback.answer()
    user_recommendation_index[callback.from_user.id] = 0
    await send_recommendation(callback, callback.from_user.id)


@router.callback_query(F.data == "recs:ai")
async def cb_recs_ai(callback: CallbackQuery):
    await callback.answer()
    user_ai_recommendation_cards[callback.from_user.id] = []
    user_ai_recommendation_index[callback.from_user.id] = 0

    await callback.message.answer("Подбираю AI-рекомендации под твой профиль...")
    await send_ai_recommendation_card(callback, callback.from_user.id)

def format_ai_event_card(event: dict) -> str:
    topics = ", ".join(event.get("topics", []))

    return (
        f"🤖 <b>AI-рекомендация</b>\n\n"
        f"<b>{esc(event['title'])}</b>\n\n"
        f"Тема: {esc(topics)}\n"
        f"Формат: {esc(event['format'])}\n"
        f"Город: {esc(event['city'])}\n"
        f"Уровень: {esc(event['level'])}\n"
        f"Дата: {esc(event['date'])}\n\n"
        f"{esc(event['description'])}\n\n"
        f"{esc(event['explanation'])}\n"
        f"Релевантность: {esc(event['score'])}"
    )


async def send_ai_recommendation_card(target: Message | CallbackQuery, telegram_id: int):
    cards = user_ai_recommendation_cards.get(telegram_id)

    if not cards:
        result = await api_client.get_agent_recommendation_cards(telegram_id)

        if not result.get("success"):
            await send(
                target,
                result.get("message", "Не удалось получить AI-рекомендации."),
            )
            return

        cards = result.get("cards", [])
        user_ai_recommendation_cards[telegram_id] = cards
        user_ai_recommendation_index[telegram_id] = 0

    if not cards:
        await send(target, "Пока нет AI-рекомендаций.")
        return

    index = user_ai_recommendation_index.get(telegram_id, 0)

    if index >= len(cards):
        user_ai_recommendation_index[telegram_id] = 0
        user_ai_recommendation_cards[telegram_id] = []
        await send(target, "Это все AI-рекомендации на сейчас.")
        return

    event = cards[index]

    interactions_data = await api_client.get_event_interactions(
        telegram_id,
        event["event_id"],
    )
    actions = set(interactions_data.get("actions", []))

    await send(
        target,
        format_ai_event_card(event),
        reply_markup=recommendation_keyboard(event["event_id"], actions, mode="ai"),
    )