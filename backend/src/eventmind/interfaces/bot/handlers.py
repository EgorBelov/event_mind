"""aiogram-хендлеры бота. Вся логика — через `BotApiClient` (HTTP к API).

Chat_id берём из `message.chat.id` (в приватном чате = пользователь). Бот
stateless: любое НЕ-командное сообщение трактуем как NL-поиск (sticky-UX из v1).
"""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from eventmind.interfaces.bot.api_client import BotApiClient
from eventmind.interfaces.bot.formatting import esc, render_event_card
from eventmind.interfaces.bot.keyboards import feedback_keyboard, more_keyboard
from eventmind.interfaces.bot.telegram import send

_logger = structlog.get_logger("eventmind.bot")
router = Router(name="eventmind")

_HELP = (
    "Я — бот EventMind. Показываю персональные IT-мероприятия и учусь на вашем "
    "фидбеке.\n\n"
    "• /feed — лента рекомендаций\n"
    "• /search &lt;запрос&gt; — поиск обычной фразой (или просто напишите текст)\n\n"
    "Чтобы получать персональную ленту, привяжите Telegram в веб-кабинете "
    "(«Настройки → Привязка Telegram») и откройте выданную ссылку."
)

_NOT_LINKED = (
    "Этот Telegram ещё не привязан к аккаунту. Откройте веб-кабинет EventMind → "
    "«Настройки → Привязка Telegram» и перейдите по ссылке. NL-поиск доступен "
    "и без привязки — просто напишите запрос."
)


def _chat_id(event: Message | CallbackQuery) -> str | None:
    message = event if isinstance(event, Message) else event.message
    if not isinstance(message, Message):
        return None
    return str(message.chat.id)


@router.message(CommandStart(deep_link=True))
async def start_with_token(message: Message, command: CommandObject, api: BotApiClient) -> None:
    chat_id = _chat_id(message)
    token = (command.args or "").strip()
    if not chat_id or not token:
        await send(message, _HELP)
        return
    ok, detail = await api.confirm_link(token, chat_id)
    if ok:
        await send(message, f"✅ {esc(detail)}\n\nОткройте /feed — покажу рекомендации.")
    else:
        await send(message, f"⚠️ {esc(detail)}")


@router.message(CommandStart())
async def start(message: Message, api: BotApiClient) -> None:
    await send(message, _HELP)


@router.message(Command("feed"))
async def feed(message: Message, api: BotApiClient) -> None:
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    items = await api.recommendations(chat_id)
    if not items:
        linked = await api.status(chat_id)
        await send(
            message,
            "Пока нечего показать — загляните позже."
            if linked
            else _NOT_LINKED,
        )
        return
    for it in items:
        await send(
            message,
            render_event_card(it, score=_as_float(it.get("score"))),
            reply_markup=feedback_keyboard(int(it["event_id"])),
        )


@router.message(Command("search"))
async def search_cmd(message: Message, command: CommandObject, api: BotApiClient) -> None:
    query = (command.args or "").strip()
    if not query:
        await send(
            message,
            "Напишите запрос после команды: <code>/search AI-конференции в июне</code>",
        )
        return
    await _run_search(message, query, api)


@router.message(F.text & ~F.text.startswith("/"))
async def freeform_search(message: Message, api: BotApiClient) -> None:
    await _run_search(message, (message.text or "").strip(), api)


async def _run_search(message: Message, query: str, api: BotApiClient) -> None:
    if not query:
        return
    result = await api.nl_search(query, limit=5)
    events = result.get("results") or []
    if not events:
        await send(message, "🔍 Ничего не нашлось. Попробуйте переформулировать.")
        return
    if result.get("relaxed"):
        await send(message, "Точных совпадений нет — вот ближайшее по смыслу:")
    for ev in events:
        await send(
            message,
            render_event_card(ev),
            reply_markup=more_keyboard(int(ev["id"]), ev.get("source_url")),
        )


@router.callback_query(F.data.regexp(r"^(like|save|hide):\d+$"))
async def on_feedback(callback: CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(callback)
    data = callback.data or ""
    action, _, raw_id = data.partition(":")
    api_action = {"like": "like", "save": "save", "hide": "dislike"}[action]
    ok = False
    if chat_id is not None:
        ok = await api.interact(chat_id, int(raw_id), api_action)
    labels = {"like": "👍 учтено", "save": "⭐ сохранено", "hide": "👎 скрыто"}
    await callback.answer(labels[action] if ok else "Сначала привяжите аккаунт", show_alert=not ok)


@router.callback_query(F.data.regexp(r"^more:\d+$"))
async def on_more(callback: CallbackQuery, api: BotApiClient) -> None:
    data = callback.data or ""
    _, _, raw_id = data.partition(":")
    ev = await api.event(int(raw_id))
    if ev is None:
        await callback.answer("Событие не найдено", show_alert=True)
        return
    await send(
        callback,
        render_event_card(ev),
        reply_markup=more_keyboard(ev["id"], ev.get("source_url")),
    )
    await callback.answer()


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
