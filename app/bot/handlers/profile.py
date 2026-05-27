import contextlib
import json

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.inline import (
    CITY_LABELS,
    FORMAT_LABELS,
    TOPIC_LABELS,
    more_menu_keyboard,
    profile_actions_keyboard,
)
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, send
from app.core.topics import city_label, format_label, topic_title


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
    events = await api_client.get_saved_events(telegram_id)
    if not events:
        await send(target, "У тебя пока нет сохраненных событий.")
        return

    chunks = [
        f"<b>{esc(e['title'])}</b>\n"
        f"Тема: {esc(', '.join(_topic(t) for t in e.get('topics', [])))}\n"
        f"Формат: {esc(_format(e['format']))}\n"
        f"Город: {esc(_city(e['city']))}\n"
        f"Дата: {esc(e['date'])}"
        for e in events
    ]
    await send(target, "<b>Сохраненные события:</b>\n\n" + "\n\n".join(chunks))


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
    stats = await api_client.get_user_stats(telegram_id)
    if not stats or not stats.get("success", True):
        await send(target, "Статистика пока недоступна. Сначала настрой профиль через /start.")
        return

    top_topics = stats.get("top_topics") or []
    last_actions = stats.get("last_actions") or []

    top_text = "\n".join(f"- {esc(_topic(t['topic']))}: {esc(t['score'])}" for t in top_topics) or "пусто"
    last_text = "\n".join(
        f"- [{esc(ACTION_LABELS.get(i['action'], i['action']))}] {esc(i['event_title'])}"
        for i in last_actions
    ) or "нет действий"

    await send(
        target,
        f"<b>Моя активность</b>\n\n"
        f"Интересно: {esc(stats.get('likes_count', 0))}\n"
        f"Не интересно: {esc(stats.get('dislikes_count', 0))}\n"
        f"Сохранено: {esc(stats.get('saves_count', 0))}\n\n"
        f"<b>Топ тем:</b>\n{top_text}\n\n"
        f"<b>Последние действия:</b>\n{last_text}",
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


def _ascii_bar_chart(topic_counts: list[tuple[str, int]], width: int = 18) -> str:
    """ASCII-горизонтальная гистограмма по топу тем за неделю.

    `topic_counts` — список (название, score) уже в порядке убывания.
    width — максимальное число символов в самом длинном баре.
    """
    if not topic_counts:
        return ""
    max_val = max(n for _, n in topic_counts) or 1
    name_w = max(len(name) for name, _ in topic_counts)
    lines: list[str] = []
    for name, val in topic_counts:
        bar_len = max(1, round(width * val / max_val))
        bar = "█" * bar_len
        lines.append(f"{name.ljust(name_w)} │ {bar} {val}")
    return "<pre>" + "\n".join(lines) + "</pre>"


async def _send_trending(target: Message | CallbackQuery):
    result = await api_client.get_trending()
    if not result:
        await send(target, "Тренды пока недоступны.")
        return

    hot_events = result.get("hot_events", [])
    trending_topics = result.get("trending_topics", [])

    # ASCII-бар-чарт по топ-5 темам — заменяет старую запятую-строку.
    topic_chart = _ascii_bar_chart(
        [(_topic(t), int(n)) for t, n in trending_topics[:5]],
        width=18,
    )
    if not topic_chart:
        topic_chart = "<i>пока нет данных</i>"

    if hot_events:
        events_text = "\n\n".join(
            f"<b>{esc(e['title'])}</b>\n"
            f"Формат: {esc(_format(e.get('format')))}\n"
            f"Дата: {esc(e.get('date', ''))}\n"
            f"Рейтинг: {esc(e.get('trending_score', '?'))}"
            for e in hot_events[:5]
        )
    else:
        events_text = "Пока недостаточно данных."

    await send(
        target,
        f"<b>🔥 Тренды IT-событий за 7 дней</b>\n\n"
        f"<b>Горячие темы:</b>\n{topic_chart}\n\n"
        f"<b>Популярные события:</b>\n\n{events_text}",
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

    answer_text = esc(result.get("answer", ""))
    cards = result.get("cards", [])

    text = answer_text
    if cards:
        events_text = "\n\n".join(
            f"📌 <b>{esc(c['title'])}</b>\n"
            f"Формат: {esc(_format(c.get('format')))}\n"
            f"Дата: {esc(c.get('date', ''))}"
            + (f"\n🔗 {esc(c['source_url'])}" if c.get("source_url") else "")
            for c in cards
        )
        text = f"{answer_text}\n\n<b>Рекомендованные события:</b>\n\n{events_text}"

    # Лимит сообщения в Telegram — 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "..."

    await send(message, text)


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
    with contextlib.suppress(Exception):
        await callback.message.edit_reply_markup(
            reply_markup=profile_actions_keyboard(is_subscribed_now)
        )


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
    await send(
        callback,
        "<b>Команды EventMind:</b>\n\n"
        "/start — настроить профиль\n"
        "/profile — мой профиль и быстрые действия\n"
        "/recommend — обычные рекомендации\n"
        "/search &lt;запрос&gt; — поиск по ключевым словам\n"
        "/semantic &lt;запрос&gt; — AI-поиск по смыслу\n"
        "/copilot &lt;цель&gt; — AI Copilot под твою цель\n"
        "/bio &lt;текст&gt; — описать себя и обновить темы\n"
        "/trending — горячие события\n"
        "/saved — сохранённые события\n"
        "/stats — моя активность\n"
        "/subscribe, /unsubscribe — управлять AI-дайджестом",
    )
