"""Единый поиск: keyword + semantic в одном ответе.

Старые команды /search и /semantic удалены. Вход — текстовая reply-кнопка
«🔍 Поиск» или префикс «Найти: <запрос>». Бэкенд возвращает два блока
(точные / по смыслу) и флаг goal_intent. Если запрос «целеполагающий»
(длинный, со словами вроде «хочу», «план», «карьера») — после результатов
показываем кнопку «🤖 Спросить Copilot по этой цели». Это гибрид: пользователь
сам решает, нужен ли AI-агент, а не угадываем за него.
"""
import time

from aiogram import F, Router
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.inline import CITY_LABELS, FORMAT_LABELS, TOPIC_LABELS
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, send
from app.core.topics import city_label, format_label, topic_title

router = Router()
api_client = EventMindAPIClient()

# Последний поисковый запрос пользователя — чтобы кнопка «🤖 Спросить
# Copilot по этой цели» могла его достать (в callback_data Telegram влезает
# только ~64 байта, длинный запрос туда не запихнёшь).
_last_query: dict[int, str] = {}


def get_last_query(user_id: int) -> str | None:
    """Внешний accessor для copilot handler — он импортирует и тащит."""
    return _last_query.get(user_id)


def is_search_waiting(user_id: int) -> bool:
    """Внешний accessor: ждём ли мы от пользователя поисковый запрос."""
    return _is_search_waiting(user_id)

# Простой in-memory state «ждём поисковый запрос от этого пользователя».
# Хранит timestamp активации; сбрасывается через 5 минут — чтобы случайные
# сообщения через час не интерпретировались как поиск.
_search_waiting: dict[int, float] = {}
_SEARCH_WAIT_TTL = 300.0  # 5 минут

# Тексты reply-кнопок главного меню — они не должны попадать в поиск.
_RESERVED_TEXTS = {
    "🎯 Рекомендации",
    "🔍 Поиск",
    "👤 Профиль",
    "⚙️ Ещё",
    "🔥 Тренды",
    "🎯 Copilot",
    "❓ Помощь",
}


def _format_event_line(event: dict, show_similarity: bool = False) -> str:
    topics = ", ".join(
        TOPIC_LABELS.get(t) or topic_title(t) for t in event.get("topics", [])
    )
    fmt = FORMAT_LABELS.get(event.get("format")) or format_label(event.get("format"))
    city = CITY_LABELS.get(event.get("city")) or city_label(event.get("city"))
    summary = (event.get("summary") or event.get("description") or "")[:160]

    sim_text = ""
    if show_similarity and event.get("similarity") is not None:
        sim_text = f" · сходство {event['similarity']:.0%}"

    return (
        f"<b>{esc(event['title'])}</b>{esc(sim_text)}\n"
        f"Темы: {esc(topics)} · Формат: {esc(fmt)} · Город: {esc(city)}\n"
        f"Дата: {esc(event.get('date', ''))}\n"
        f"{esc(summary)}"
    )


def _format_combined_result(query: str, result: dict) -> str:
    keyword = result.get("keyword", [])
    semantic = result.get("semantic", [])

    if not keyword and not semantic:
        return f"По запросу «{esc(query)}» ничего не нашлось."

    parts: list[str] = [f"Результаты по запросу «<b>{esc(query)}</b>»:\n"]

    if keyword:
        parts.append("🎯 <b>Точные совпадения:</b>\n")
        parts.extend(_format_event_line(e) for e in keyword)
    else:
        parts.append("🎯 <b>Точных совпадений нет</b>, но есть похожие по смыслу:\n")

    if semantic:
        parts.append("\n🤖 <b>Похожие по смыслу:</b>\n")
        parts.extend(_format_event_line(e, show_similarity=True) for e in semantic)

    return "\n\n".join(parts)


def _copilot_offer_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Спросить Copilot по этой цели", callback_data="copilot_from_search")
    return builder.as_markup()


async def _do_search(message: Message, query: str) -> None:
    query = query.strip()
    if not query:
        await send(message, "Пустой запрос. Напиши что-нибудь, например: <code>python митап</code>")
        return

    # Новый явный поиск → сбрасываем активную Copilot-сессию, чтобы её ответы
    # не «склеивались» с несвязанным новым запросом.
    from app.bot.handlers.copilot import reset_session_for_user
    reset_session_for_user(message.from_user.id)

    # Всегда запоминаем запрос — кнопка Copilot теперь доступна всегда.
    _last_query[message.from_user.id] = query

    result = await api_client.combined_search(query=query, keyword_limit=3, semantic_limit=5)
    text = _format_combined_result(query, result)

    if result.get("goal_intent"):
        text += (
            "\n\n💡 Похоже, ты описываешь карьерную цель. Если нужен пошаговый "
            "план или анализ скиллов — нажми кнопку ниже, AI-Copilot ответит развёрнуто."
        )
    else:
        text += "\n\n🤖 Можно задать тот же запрос Copilot'у — он подберёт план и сможет продолжить диалог."

    await send(message, text, reply_markup=_copilot_offer_keyboard())


def _is_search_waiting(user_id: int) -> bool:
    ts = _search_waiting.get(user_id)
    if ts is None:
        return False
    if time.time() - ts > _SEARCH_WAIT_TTL:
        _search_waiting.pop(user_id, None)
        return False
    return True


# ─── Триггеры ─────────────────────────────────────────────────────────────


@router.message(F.text == "🔍 Поиск")
async def msg_search_prompt(message: Message):
    """Reply-кнопка → ждём следующее сообщение пользователя как запрос."""
    _search_waiting[message.from_user.id] = time.time()
    await send(
        message,
        "🔍 <b>Поиск событий</b>\n\n"
        "Напиши, что искать — одним сообщением.\n"
        "Можно ключевыми словами (<code>python митап</code>) или по смыслу "
        "(<code>хочу научиться деплоить микросервисы</code>).\n\n"
        "Покажу до 3 точных совпадений и до 5 похожих по смыслу.",
    )


@router.message(F.text.startswith("Найти:"))
async def msg_search_prefix(message: Message):
    """Совместимость со старым префиксом «Найти: <запрос>»."""
    query = message.text.split(":", 1)[1]
    await _do_search(message, query)


def _pending_search_filter(message: Message) -> bool:
    """Срабатываем ТОЛЬКО если: (1) пользователь в waiting-state, (2) текст не
    зарезервированная reply-кнопка, (3) не slash-команда. Иначе — пропускаем
    сообщение дальше другим хендлерам без вызова body."""
    if not message.text:
        return False
    if message.text.startswith("/"):
        return False
    if message.text in _RESERVED_TEXTS:
        return False
    if message.text.startswith("Найти:"):
        return False  # есть отдельный handler выше
    return _is_search_waiting(message.from_user.id)


@router.message(_pending_search_filter)
async def msg_pending_search(message: Message):
    _search_waiting.pop(message.from_user.id, None)
    await _do_search(message, message.text)
