import json

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import (
    TOPIC_LABELS,
    FORMAT_LABELS,
    CITY_LABELS,
    profile_actions_keyboard,
    more_menu_keyboard,
)
from app.core.topics import topic_title, format_label, city_label


def _topic(code: str) -> str:
    return TOPIC_LABELS.get(code) or topic_title(code)


def _format(code: str | None) -> str:
    if not code:
        return "не выбран"
    return FORMAT_LABELS.get(code) or format_label(code)


def _city(code: str | None) -> str:
    if not code:
        return "не выбран"
    return CITY_LABELS.get(code) or city_label(code)

router = Router()
api_client = EventMindAPIClient()

ACTION_LABELS = {
    "like": "Интересно",
    "dislike": "Не интересно",
    "save": "Сохранено",
}


async def _render_profile(target: Message | CallbackQuery, telegram_id: int):
    user = await api_client.get_user(telegram_id)
    answer = target.answer if isinstance(target, Message) else target.message.answer
    if not user:
        await answer("Профиль пока не настроен. Запусти /start")
        return

    topics = ", ".join(_topic(t) for t in user.get("topics", [])) or "не выбраны"
    preferred_format = _format(user.get("preferred_format"))
    city = _city(user.get("city"))

    topic_weights_raw = user.get("topic_weights", "{}")
    try:
        topic_weights = json.loads(topic_weights_raw) if isinstance(topic_weights_raw, str) else topic_weights_raw
    except json.JSONDecodeError:
        topic_weights = {}

    weights_text = (
        "\n".join(f"- {_topic(t)}: {w}" for t, w in topic_weights.items())
        if topic_weights else "пока не сформированы"
    )

    await answer(
        f"Твой профиль:\n\n"
        f"Темы: {topics}\n"
        f"Формат: {preferred_format}\n"
        f"Город: {city}\n\n"
        f"Веса интересов:\n{weights_text}",
        reply_markup=profile_actions_keyboard(bool(user.get("is_subscribed"))),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    await _render_profile(message, message.from_user.id)


async def _send_saved(target: Message | CallbackQuery, telegram_id: int):
    answer = target.answer if isinstance(target, Message) else target.message.answer
    events = await api_client.get_saved_events(telegram_id)
    if not events:
        await answer("У тебя пока нет сохраненных событий.")
        return

    chunks = [
        f"*{e['title']}*\n"
        f"Тема: {', '.join(_topic(t) for t in e.get('topics', []))}\n"
        f"Формат: {_format(e['format'])}\n"
        f"Город: {_city(e['city'])}\n"
        f"Дата: {e['date']}"
        for e in events
    ]
    await answer("*Сохраненные события:*\n\n" + "\n\n".join(chunks), parse_mode="Markdown")


@router.message(Command("saved"))
async def cmd_saved(message: Message):
    await _send_saved(message, message.from_user.id)


@router.message(F.text == "👤 Профиль")
async def msg_profile(message: Message):
    await _render_profile(message, message.from_user.id)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    await _send_stats(message, message.from_user.id)


async def _send_stats(target: Message | CallbackQuery, telegram_id: int):
    answer = target.answer if isinstance(target, Message) else target.message.answer
    stats = await api_client.get_user_stats(telegram_id)
    if not stats or not stats.get("success", True):
        await answer("Статистика пока недоступна. Сначала настрой профиль через /start.")
        return

    top_topics = stats.get("top_topics") or []
    last_actions = stats.get("last_actions") or []

    top_text = "\n".join(f"- {_topic(t['topic'])}: {t['score']}" for t in top_topics) or "пусто"
    last_text = "\n".join(f"- [{ACTION_LABELS.get(i['action'], i['action'])}] {i['event_title']}" for i in last_actions) or "нет действий"

    await answer(
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
    topic_text = ", ".join(_topic(t) for t in topics)
    await message.answer(f"Готово. По описанию обновил твои темы: {topic_text}.")


async def _send_trending(target: Message | CallbackQuery):
    answer = target.answer if isinstance(target, Message) else target.message.answer
    result = await api_client.get_trending()
    if not result:
        await answer("Тренды пока недоступны.")
        return

    hot_events = result.get("hot_events", [])
    trending_topics = result.get("trending_topics", [])

    topics_text = ", ".join(
        f"{_topic(t)} ({n})" for t, n in trending_topics[:5]
    ) or "пока нет данных"

    if hot_events:
        events_text = "\n\n".join(
            f"*{e['title']}*\n"
            f"Формат: {_format(e.get('format'))}\n"
            f"Дата: {e.get('date', '')}\n"
            f"Рейтинг: {e.get('trending_score', '?')}"
            for e in hot_events[:5]
        )
    else:
        events_text = "Пока недостаточно данных."

    await answer(
        f"*Тренды IT-событий*\n\n"
        f"*Горячие темы:* {topics_text}\n\n"
        f"*Популярные события:*\n\n{events_text}",
        parse_mode="Markdown",
    )


@router.message(Command("trending"))
async def cmd_trending(message: Message):
    await _send_trending(message)


@router.message(Command("copilot"))
async def cmd_copilot(message: Message, command: CommandObject):
    """AI Copilot: расскажи цель — получишь персональный roadmap по событиям."""
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
            f"Формат: {_format(c.get('format'))}\n"
            f"Дата: {c.get('date', '')}"
            + (f"\n🔗 {c['source_url']}" if c.get("source_url") else "")
            for c in cards
        )
        text = f"{answer}\n\n*Рекомендованные события:*\n\n{events_text}"

    # Лимит сообщения в Telegram — 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "..."

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "⚙️ Ещё")
async def msg_more(message: Message):
    await message.answer(
        "Дополнительные функции:",
        reply_markup=more_menu_keyboard(),
    )


@router.callback_query(F.data == "profile:saved")
async def cb_profile_saved(callback: CallbackQuery):
    await callback.answer()
    await _send_saved(callback, callback.from_user.id)


@router.callback_query(F.data == "profile:stats")
async def cb_profile_stats(callback: CallbackQuery):
    await callback.answer()
    await _send_stats(callback, callback.from_user.id)


@router.callback_query(F.data == "profile:toggle_digest")
async def cb_profile_toggle_digest(callback: CallbackQuery):
    user = await api_client.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала настрой профиль через /start", show_alert=True)
        return

    was_subscribed = bool(user.get("is_subscribed"))
    if was_subscribed:
        result = await api_client.unsubscribe(callback.from_user.id)
    else:
        result = await api_client.subscribe(callback.from_user.id)

    is_subscribed_now = not was_subscribed
    await callback.answer(result.get("message", "Готово."))
    try:
        await callback.message.edit_reply_markup(
            reply_markup=profile_actions_keyboard(is_subscribed_now)
        )
    except Exception:
        pass


@router.callback_query(F.data == "more:trending")
async def cb_more_trending(callback: CallbackQuery):
    await callback.answer()
    await _send_trending(callback)


@router.callback_query(F.data == "more:copilot")
async def cb_more_copilot(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "AI Copilot подбирает события под твою цель.\n\n"
        "Использование: /copilot <цель>\n"
        "Например: /copilot хочу разобраться в Kubernetes и SRE"
    )


@router.callback_query(F.data == "more:help")
async def cb_more_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "*Команды EventMind:*\n\n"
        "/start — настроить профиль\n"
        "/profile — мой профиль и быстрые действия\n"
        "/recommend — обычные рекомендации\n"
        "/search <запрос> — поиск по ключевым словам\n"
        "/semantic <запрос> — AI-поиск по смыслу\n"
        "/copilot <цель> — AI Copilot под твою цель\n"
        "/bio <текст> — описать себя и обновить темы\n"
        "/trending — горячие события\n"
        "/saved — сохранённые события\n"
        "/stats — моя активность\n"
        "/subscribe, /unsubscribe — управлять AI-дайджестом",
        parse_mode="Markdown",
    )
