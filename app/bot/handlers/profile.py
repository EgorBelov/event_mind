import json

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS

router = Router()
api_client = EventMindAPIClient()


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user = await api_client.get_user(message.from_user.id)

    if user.get("message") == "User not found":
        await message.answer("Профиль пока не настроен. Запусти /start")
        return

    topics = ", ".join(TOPIC_LABELS.get(topic, topic) for topic in user.get("topics", [])) or "не выбраны"
    preferred_format = user.get("preferred_format") or "не выбран"
    city = user.get("city") or "не выбран"

    topic_weights_raw = user.get("topic_weights", "{}")
    try:
        topic_weights = json.loads(topic_weights_raw) if isinstance(topic_weights_raw, str) else topic_weights_raw
    except json.JSONDecodeError:
        topic_weights = {}

    if topic_weights:
        weights_text = "\n".join(
            f"- {TOPIC_LABELS.get(topic, topic)}: {weight}"
            for topic, weight in topic_weights.items()
        )
    else:
        weights_text = "пока не сформированы"

    await message.answer(
        f"Твой профиль:\n\n"
        f"Темы: {topics}\n"
        f"Формат: {preferred_format}\n"
        f"Город: {city}\n\n"
        f"Веса интересов:\n{weights_text}"
    )