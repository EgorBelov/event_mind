import json

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS, FORMAT_LABELS, CITY_LABELS

router = Router()
api_client = EventMindAPIClient()


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user = await api_client.get_user(message.from_user.id)

    if not user:
        await message.answer("Профиль пока не настроен. Запусти /start")
        return

    topics = ", ".join(TOPIC_LABELS.get(topic, topic) for topic in user.get("topics", [])) or "не выбраны"
    preferred_format = FORMAT_LABELS.get(user.get("preferred_format"), user.get("preferred_format") or "не выбран")
    city = CITY_LABELS.get(user.get("city"), user.get("city") or "не выбран")

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


@router.message(Command("saved"))
async def cmd_saved(message: Message):
    events = await api_client.get_saved_events(message.from_user.id)

    if not events:
        await message.answer("У тебя пока нет сохраненных событий.")
        return

    chunks = []
    for event in events:
        topics = ", ".join(TOPIC_LABELS.get(topic, topic) for topic in event.get("topics", []))
        format_label = FORMAT_LABELS.get(event["format"], event["format"])
        city_label = CITY_LABELS.get(event["city"], event["city"])

        chunks.append(
            f"*{event['title']}*\n"
            f"Тема: {topics}\n"
            f"Формат: {format_label}\n"
            f"Город: {city_label}\n"
            f"Дата: {event['date']}"
        )

    text = "*Сохраненные события:*\n\n" + "\n\n".join(chunks)
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "Профиль")
async def msg_profile(message: Message):
    await cmd_profile(message)


@router.message(F.text == "Избранное")
async def msg_saved(message: Message):
    await cmd_saved(message)
