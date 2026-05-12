import json

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS, FORMAT_LABELS, CITY_LABELS

router = Router()
api_client = EventMindAPIClient()


ACTION_LABELS = {
    "like": "Интересно",
    "dislike": "Не интересно",
    "save": "Сохранено",
}


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


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    await _send_stats(message)


@router.message(F.text == "Моя активность")
async def msg_stats(message: Message):
    await _send_stats(message)


async def _send_stats(message: Message):
    stats = await api_client.get_user_stats(message.from_user.id)
    if not stats or not stats.get("success", True):
        await message.answer("Статистика пока недоступна. Сначала настрой профиль через /start.")
        return

    top_topics = stats.get("top_topics") or []
    last_actions = stats.get("last_actions") or []

    top_topics_text = "\n".join(
        f"- {TOPIC_LABELS.get(t['topic'], t['topic'])}: {t['score']}"
        for t in top_topics
    ) or "пока пусто"

    last_actions_text = "\n".join(
        f"- [{ACTION_LABELS.get(item['action'], item['action'])}] {item['event_title']}"
        for item in last_actions
    ) or "ещё нет действий"

    text = (
        "*Моя активность*\n\n"
        f"Интересно: {stats.get('likes_count', 0)}\n"
        f"Не интересно: {stats.get('dislikes_count', 0)}\n"
        f"Сохранено: {stats.get('saves_count', 0)}\n\n"
        f"*Топ тем по интересу:*\n{top_topics_text}\n\n"
        f"*Последние действия:*\n{last_actions_text}"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("bio"))
async def cmd_bio(message: Message, command: CommandObject):
    bio_text = (command.args or "").strip()
    if not bio_text:
        await message.answer(
            "Расскажи о себе одной строкой после команды.\n"
            "Например: /bio Я Python разработчик, интересуюсь AI/ML и DevOps."
        )
        return

    result = await api_client.analyze_bio(message.from_user.id, bio_text)
    if not result.get("success"):
        await message.answer(result.get("message", "Не удалось обработать bio."))
        return

    topics = result.get("extracted_topics", [])
    topic_text = ", ".join(TOPIC_LABELS.get(t, t) for t in topics)
    await message.answer(
        f"Готово. По описанию я обновил твои темы: {topic_text}.",
    )
