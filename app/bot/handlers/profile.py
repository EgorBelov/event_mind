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

    topics = ", ".join(TOPIC_LABELS.get(t, t) for t in user.get("topics", [])) or "не выбраны"
    preferred_format = FORMAT_LABELS.get(user.get("preferred_format"), user.get("preferred_format") or "не выбран")
    city = CITY_LABELS.get(user.get("city"), user.get("city") or "не выбран")

    topic_weights_raw = user.get("topic_weights", "{}")
    try:
        topic_weights = json.loads(topic_weights_raw) if isinstance(topic_weights_raw, str) else topic_weights_raw
    except json.JSONDecodeError:
        topic_weights = {}

    weights_text = (
        "\n".join(f"- {TOPIC_LABELS.get(t, t)}: {w}" for t, w in topic_weights.items())
        if topic_weights else "пока не сформированы"
    )

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

    chunks = [
        f"*{e['title']}*\n"
        f"Тема: {', '.join(TOPIC_LABELS.get(t, t) for t in e.get('topics', []))}\n"
        f"Формат: {FORMAT_LABELS.get(e['format'], e['format'])}\n"
        f"Город: {CITY_LABELS.get(e['city'], e['city'])}\n"
        f"Дата: {e['date']}"
        for e in events
    ]
    await message.answer("*Сохраненные события:*\n\n" + "\n\n".join(chunks), parse_mode="Markdown")


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

    top_text = "\n".join(f"- {TOPIC_LABELS.get(t['topic'], t['topic'])}: {t['score']}" for t in top_topics) or "пусто"
    last_text = "\n".join(f"- [{ACTION_LABELS.get(i['action'], i['action'])}] {i['event_title']}" for i in last_actions) or "нет действий"

    await message.answer(
        f"*Моя активность*\n\n"
        f"Интересно: {stats.get('likes_count', 0)}\n"
        f"Не интересно: {stats.get('dislikes_count', 0)}\n"
        f"Сохранено: {stats.get('saves_count', 0)}\n\n"
        f"*Топ тем:*\n{top_text}\n\n"
        f"*Последние действия:*\n{last_text}",
        parse_mode="Markdown",
    )


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
    await message.answer(f"Готово. По описанию обновил твои темы: {topic_text}.")


@router.message(Command("trending"))
async def cmd_trending(message: Message):
    """Show trending IT events and hot topics."""
    result = await api_client.get_trending()
    if not result:
        await message.answer("Тренды пока недоступны.")
        return

    hot_events = result.get("hot_events", [])
    trending_topics = result.get("trending_topics", [])

    topics_text = ", ".join(
        f"{TOPIC_LABELS.get(t, t)} ({n})" for t, n in trending_topics[:5]
    ) or "пока нет данных"

    if hot_events:
        events_text = "\n\n".join(
            f"*{e['title']}*\n"
            f"Формат: {FORMAT_LABELS.get(e.get('format'), e.get('format', ''))}\n"
            f"Дата: {e.get('date', '')}\n"
            f"Рейтинг: {e.get('trending_score', '?')}"
            for e in hot_events[:5]
        )
    else:
        events_text = "Пока недостаточно данных."

    await message.answer(
        f"*Тренды IT-событий*\n\n"
        f"*Горячие темы:* {topics_text}\n\n"
        f"*Популярные события:*\n\n{events_text}",
        parse_mode="Markdown",
    )


@router.message(Command("copilot"))
async def cmd_copilot(message: Message, command: CommandObject):
    """AI Copilot: tell your goal and get a personalised event roadmap."""
    goal = (command.args or "").strip()
    if not goal:
        await message.answer(
            "Расскажи о своей цели, и я подберу события и составлю план.\n\n"
            "Например:\n"
            "/copilot хочу разобраться в DevOps и начать использовать Kubernetes\n"
            "/copilot ищу события для перехода в ML-разработку"
        )
        return

    await message.answer("Анализирую твою цель и подбираю события...")

    result = await api_client.copilot(message.from_user.id, goal)

    if not result.get("success"):
        await message.answer(result.get("message", "Copilot временно недоступен. Попробуй позже."))
        return

    answer = result.get("answer", "")
    cards = result.get("cards", [])

    text = answer
    if cards:
        events_text = "\n\n".join(
            f"📌 *{c['title']}*\n"
            f"Формат: {FORMAT_LABELS.get(c.get('format'), c.get('format', ''))}\n"
            f"Дата: {c.get('date', '')}"
            + (f"\n🔗 {c['source_url']}" if c.get("source_url") else "")
            for c in cards
        )
        text = f"{answer}\n\n*Рекомендованные события:*\n\n{events_text}"

    # Telegram message limit: 4096 chars
    if len(text) > 4000:
        text = text[:4000] + "..."

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "Тренды")
async def msg_trending(message: Message):
    await cmd_trending(message)
