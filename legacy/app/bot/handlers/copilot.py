"""AI Copilot — мульти-туровый диалог через Telegram-бота.

Поведение:
- /copilot <цель> или callback из поиска → стартует НОВУЮ сессию (closing старую,
  если была).
- После ответа Copilot выставляется per-user state: сессия активна N секунд.
  Любое следующее текстовое сообщение (не команда, не reply-кнопка, не
  «Найти:...», не pending_search) — продолжает сессию через /copilot/turn,
  и AI помнит контекст предыдущих реплик.
- Сессия живёт на бэкенде в таблице copilot_sessions; в боте мы храним только
  session_id и timestamp в RAM.
"""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, send

router = Router()
api_client = EventMindAPIClient()


# Активные сессии: user_id -> {session_id, last_activity}.
# TTL — 15 минут: после этого следующее сообщение НЕ продолжает диалог
# автоматически (пользователь явно начнёт через кнопку или /copilot).
_active_sessions: dict[int, dict] = {}
_SESSION_TTL = 900.0

# Тексты reply-кнопок главного меню — не интерпретируем их как сообщения Copilot.
_RESERVED_TEXTS = {
    "🎯 Рекомендации", "🔍 Поиск", "👤 Профиль", "⚙️ Ещё",
    "🔥 Тренды", "❓ Помощь", "Начать настройку", "Как это работает",
}


def _is_session_active(user_id: int) -> bool:
    rec = _active_sessions.get(user_id)
    if not rec:
        return False
    if time.time() - rec.get("last_activity", 0) > _SESSION_TTL:
        _active_sessions.pop(user_id, None)
        return False
    return True


def _get_active_session_id(user_id: int) -> int | None:
    if _is_session_active(user_id):
        return _active_sessions[user_id].get("session_id")
    return None


def _set_active_session(user_id: int, session_id: int | None) -> None:
    if session_id is None:
        return
    _active_sessions[user_id] = {
        "session_id": session_id,
        "last_activity": time.time(),
    }


def _reset_session(user_id: int) -> None:
    _active_sessions.pop(user_id, None)


def _format_copilot_response(result: dict) -> str:
    """Привести ответ Copilot к HTML-сообщению с экранированием контента и
    с подписями специалиста / турна."""
    answer = result.get("answer") or "Copilot не вернул текстовый ответ."
    specialist = result.get("specialist") or "copilot"
    turns = result.get("turns")
    cards = result.get("cards") or []

    header = f"🤖 <b>Copilot · {esc(specialist)}</b>"
    if turns:
        header += f" · ход {turns}"

    parts = [header, "", esc(answer)]
    if cards:
        parts.append("")
        parts.append("<b>Рекомендованные события:</b>")
        for c in cards[:5]:
            block = (
                f"📌 <b>{esc(c.get('title', ''))}</b>\n"
                f"Формат: {esc(c.get('format', ''))} · "
                f"Город: {esc(c.get('city', ''))} · "
                f"Дата: {esc(c.get('date', ''))}"
            )
            if c.get("source_url"):
                block += f"\n🔗 {esc(c['source_url'])}"
            parts.append(block)

    text = "\n".join(parts)
    if len(text) > 4000:
        text = text[:4000] + "…"
    return text


async def _start_or_continue(
    target: Message | CallbackQuery,
    user_id: int,
    message_text: str,
    *,
    reset: bool = False,
) -> None:
    """Единая точка входа: либо стартуем новую сессию (reset=True или нет
    активной), либо продолжаем текущую (передаём session_id)."""
    if reset:
        _reset_session(user_id)

    session_id = _get_active_session_id(user_id)
    result = await api_client.copilot_turn(
        telegram_id=user_id,
        message=message_text,
        session_id=session_id,
    )

    if not result.get("success"):
        await send(target, result.get("message") or "Copilot временно недоступен. Попробуй позже.")
        return

    new_session_id = result.get("session_id")
    _set_active_session(user_id, new_session_id)

    await send(target, _format_copilot_response(result))


# ─── Точки входа ──────────────────────────────────────────────────────────


@router.message(Command("copilot"))
async def cmd_copilot(message: Message, command: CommandObject):
    """Slash-вход: всегда стартует НОВУЮ сессию."""
    goal = (command.args or "").strip()
    if not goal:
        await message.answer(
            "Расскажи о цели одним сообщением — Copilot подберёт события и "
            "составит план. После первого ответа можешь продолжить диалог "
            "обычными сообщениями: AI помнит контекст.\n\n"
            "Например:\n"
            "<code>/copilot хочу за полгода вырасти в middle backend</code>\n"
            "<code>/copilot подбери митапы по Kubernetes для DevOps-инженера</code>",
        )
        return
    await message.answer("🤖 Анализирую цель и подбираю события…")
    await _start_or_continue(message, message.from_user.id, goal, reset=True)


@router.callback_query(F.data == "copilot_from_search")
async def cb_copilot_from_search(callback: CallbackQuery):
    """Запустить Copilot с последним поисковым запросом пользователя как goal."""
    # Чтобы не плодить циклическую зависимость, ленивый импорт.
    from app.bot.handlers.search import get_last_query

    user_id = callback.from_user.id
    query = get_last_query(user_id)
    if not query:
        await callback.answer("Запрос потерян — повтори поиск ещё раз", show_alert=True)
        return

    await callback.answer("Запускаю Copilot…")
    await send(
        callback,
        f"🤖 <b>Copilot работает над запросом:</b>\n«{esc(query)}»\n\n"
        "Это займёт несколько секунд — он анализирует профиль, историю и подбирает план.",
    )
    await _start_or_continue(callback, user_id, query, reset=True)


# ─── Продолжение диалога обычным текстом ──────────────────────────────────


def _copilot_continue_filter(message: Message) -> bool:
    """Срабатываем ТОЛЬКО если у пользователя активная Copilot-сессия и
    сообщение похоже на ответ (не команда, не reply-кнопка, не префикс «Найти:»).
    """
    if not message.text:
        return False
    if message.text.startswith("/"):
        return False
    if message.text in _RESERVED_TEXTS:
        return False
    if message.text.startswith("Найти:"):
        return False
    # Если человек сейчас в режиме «бот ждёт поисковый запрос», отдаём приоритет
    # поиску — Copilot-ответ может прийти позже.
    from app.bot.handlers.search import is_search_waiting
    if is_search_waiting(message.from_user.id):
        return False
    return _is_session_active(message.from_user.id)


@router.message(_copilot_continue_filter)
async def msg_copilot_continue(message: Message):
    """Любое текстовое сообщение → продолжение активной Copilot-сессии."""
    await message.answer("🤖 Copilot думает…")
    await _start_or_continue(message, message.from_user.id, message.text)


# ─── Внешний API для других хендлеров ────────────────────────────────────


def reset_session_for_user(user_id: int) -> None:
    """Вызывается извне (например, при новом поиске), чтобы не «склеить»
    старый Copilot-контекст с новым неcвязанным запросом."""
    _reset_session(user_id)
