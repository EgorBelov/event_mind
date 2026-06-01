from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.inline import recommendation_keyboard
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, send

router = Router()
api_client = EventMindAPIClient()

# Курсор по ленте теперь живёт в users.feed_cursor (см. миграцию c3d4e5f6a7b8).
# Раньше был module-dict — терялся при рестарте процесса и ломался при
# нескольких воркерах. Через API он переживает и рестарт, и сценарий
# «открыл в одном клиенте, продолжил в другом».


_COMPONENT_LABELS = {
    "rule": "темы",
    "cosine": "смысл",
    "bayesian": "история",
    "quality": "качество",
    "hype": "хайп",
    "freshness": "свежесть",
    "skill_gap": "под скиллы",
    "bandit": "бандит",
    "gnn": "соседи",
}


def _why_short(event: dict) -> str:
    """Короткое объяснение для поп-апа (лимит Telegram ~200 символов).

    Берём топ-3 положительных компонента из score_breakdown.
    """
    breakdown = event.get("score_breakdown") or {}
    positive = [(name, val) for name, val in breakdown.items() if val and val > 0.05]
    if not positive:
        return "Подобрано по совпадению темы и формата с твоим профилем."
    positive.sort(key=lambda kv: kv[1], reverse=True)
    top = positive[:3]
    parts = [f"{_COMPONENT_LABELS.get(name, name)} +{val:.1f}" for name, val in top]
    return "Главные факторы: " + " · ".join(parts)


def format_event_card(event: dict) -> str:
    """Компактная карточка: только факты по событию. Объяснение — по кнопке."""
    topics = ", ".join(event.get("topics", []))

    return (
        f"<b>{esc(event['title'])}</b>\n\n"
        f"Тема: {esc(topics)}\n"
        f"Формат: {esc(event['format'])}\n"
        f"Город: {esc(event['city'])}\n"
        f"Уровень: {esc(event['level'])}\n"
        f"Дата: {esc(event['date'])}\n\n"
        f"{esc(event['description'])}"
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

    current_index = await api_client.get_feed_cursor(telegram_id)

    if current_index >= len(recommendations):
        await api_client.reset_feed_cursor(telegram_id)
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
        reply_markup=recommendation_keyboard(event["event_id"], actions),
    )


async def update_markup(callback: CallbackQuery, event_id: int) -> None:
    interactions_data = await api_client.get_event_interactions(callback.from_user.id, event_id)
    actions = set(interactions_data.get("actions", []))

    await callback.message.edit_reply_markup(
        reply_markup=recommendation_keyboard(event_id, actions)
    )


def _parse_event_cb(data: str) -> int:
    """`like:123` -> 123."""
    _, event_id = data.split(":", 1)
    return int(event_id)


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    await api_client.reset_feed_cursor(message.from_user.id)
    await send_recommendation(message, message.from_user.id)


@router.message(F.text == "🎯 Рекомендации")
async def msg_recommend(message: Message):
    """Reply-кнопка главного меню — главный способ открыть ленту."""
    await api_client.reset_feed_cursor(message.from_user.id)
    await send_recommendation(message, message.from_user.id)


@router.message(Command("undo"))
async def cmd_undo(message: Message):
    """Откатить последнее like / dislike / save."""
    result = await api_client.undo_last_interaction(message.from_user.id)
    if not result:
        await message.answer("Не удалось связаться с API.")
        return
    msg = result.get("message") or ("Готово." if result.get("success") else "Нет действий для отката.")
    await message.answer(msg)


@router.callback_query(F.data == "show_recommendations")
async def cb_show_recommendations(callback: CallbackQuery):
    await callback.answer()
    await api_client.reset_feed_cursor(callback.from_user.id)
    await send_recommendation(callback, callback.from_user.id)


@router.callback_query(F.data == "next")
async def cb_next(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer("Показываю следующее событие")
    await api_client.advance_feed_cursor(user_id)
    await send_recommendation(callback, user_id)


@router.callback_query(F.data.startswith("like:"))
async def cb_like(callback: CallbackQuery):
    event_id = _parse_event_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="like"
    )
    await callback.answer("Отмечено как интересное")
    await update_markup(callback, event_id)


@router.callback_query(F.data.startswith("dislike:"))
async def cb_dislike(callback: CallbackQuery):
    event_id = _parse_event_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="dislike"
    )
    await callback.answer("Отмечено как неинтересное")
    await update_markup(callback, event_id)


@router.callback_query(F.data.startswith("save:"))
async def cb_save(callback: CallbackQuery):
    event_id = _parse_event_cb(callback.data)
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="save"
    )
    await callback.answer("Событие сохранено")
    await update_markup(callback, event_id)


@router.callback_query(F.data.startswith("similar:"))
async def cb_similar(callback: CallbackQuery):
    """Показать события, похожие по темам."""
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


# ─── «Почему?» / «📖 Подробнее» ──────────────────────────────────────────


@router.callback_query(F.data.startswith("why:"))
async def cb_why_short(callback: CallbackQuery):
    """Короткий ответ ИИ в поп-апе (1–2 предложения, без цифр)."""
    event_id = int(callback.data.split(":", 1)[1])
    why_data = await api_client.get_why_explanation(callback.from_user.id, event_id)
    short = why_data.get("short") or "Подобрано по совпадению темы и формата с твоим профилем."
    await callback.answer(short[:200], show_alert=True)


@router.callback_query(F.data.startswith("why_full:"))
async def cb_why_full(callback: CallbackQuery):
    """Развёрнутый разбор отдельным сообщением: LLM-нарратив, советы, метрики."""
    event_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Готовлю подробное объяснение…")
    why_data = await api_client.get_why_explanation(callback.from_user.id, event_id)
    full = why_data.get("full") or why_data.get("short") or "Объяснение недоступно."
    await send(callback, f"<b>Почему именно это событие</b>\n\n{esc(full)}")
