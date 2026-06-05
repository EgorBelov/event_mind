"""Поиск событий.

Два режима под капотом:
1) NL-поиск (по умолчанию): LLM достаёт даты/город/тип события из запроса
   («конференции с 3 по 10 июня в Москве»), мы строим SQL по полям.
2) Combined-fallback: если LLM не извлёк ничего конкретного — старый
   keyword + semantic поиск.

Над каждым результатом — кнопка ⭐ «Сохранить»: реюзаем механизм
interactions(action='save'), то же действие, что в карточке рекомендации.
"""
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.inline import CITY_LABELS, FORMAT_LABELS, TOPIC_LABELS
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import esc, event_url_line, format_event_date, send
from app.core.topics import city_label, format_label, topic_title

router = Router()
api_client = EventMindAPIClient()


def is_search_waiting(user_id: int) -> bool:
    """Внешний accessor: ждём ли мы от пользователя поисковый запрос."""
    return _is_search_waiting(user_id)

# Простой in-memory state «ждём поисковый запрос от этого пользователя».
# Хранит timestamp активации; sticky — не сбрасывается после первого поиска,
# чтобы можно было задавать запросы один за другим без повторного тыка в
# reply-кнопку «🔍 Поиск». TTL 60 минут на случай длинного перерыва — после
# часа простоя случайные сообщения снова перестанут идти в поиск.
_search_waiting: dict[int, float] = {}
_SEARCH_WAIT_TTL = 3600.0  # 60 минут (было 5 — пользователи жаловались на повторный тык)


def _touch_waiting(user_id: int) -> None:
    """Продлить waiting-state — обнуляем timestamp."""
    _search_waiting[user_id] = time.time()


def clear_search_waiting(user_id: int) -> None:
    """Снять waiting-state. Используется внешними хендлерами, когда
    пользователь явно ушёл в другой раздел (если потребуется в будущем)."""
    _search_waiting.pop(user_id, None)

# Тексты reply-кнопок главного меню — они не должны попадать в поиск.
_RESERVED_TEXTS = {
    "🎯 Рекомендации",
    "🔍 Поиск",
    "👤 Профиль",
    "⚙️ Ещё",
    "🔥 Тренды",
    "❓ Помощь",
}


_MONTHS_RU_NOM = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


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
        f"Дата: {esc(format_event_date(event))}"
        f"{event_url_line(event)}\n"
        f"{esc(summary)}"
    )


def _save_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Под каждым результатом — одна кнопка ⭐ «Сохранить» (см. #8)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Сохранить", callback_data=f"search_save:{event_id}")
    return builder.as_markup()


def _new_search_keyboard() -> InlineKeyboardMarkup:
    """Якорь под последним результатом: явный «Новый поиск», чтобы пользователь
    видел, что бот всё ещё в режиме поиска и можно сразу писать."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Новый поиск", callback_data="search_new")
    return builder.as_markup()


def _recommendations_cta_keyboard() -> InlineKeyboardMarkup:
    """CTA «🎯 К рекомендациям» — показываем после fallback'а и при пустом
    поиске, чтобы пользователь не упирался в тупик."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 К рекомендациям", callback_data="show_recommendations")
    builder.button(text="🔍 Новый поиск", callback_data="search_new")
    builder.adjust(1, 1)
    return builder.as_markup()


def _humanize_iso_date(iso: str) -> str:
    """`2026-06-10` → `10 июня`. Не падаем на мусоре."""
    try:
        from datetime import date as _date
        d = _date.fromisoformat(iso)
        return f"{d.day} {_MONTHS_RU_NOM[d.month - 1]}"
    except Exception:
        return iso


def _format_filters_hint(filters: dict) -> str:
    """Подсказка «Понял как: …» — пользователь видит, что LLM извлёк."""
    parts: list[str] = []
    df, dt = filters.get("date_from"), filters.get("date_to")
    if df and dt:
        if df == dt:
            parts.append(f"дата {_humanize_iso_date(df)}")
        else:
            parts.append(f"с {_humanize_iso_date(df)} по {_humanize_iso_date(dt)}")
    elif df:
        parts.append(f"с {_humanize_iso_date(df)}")
    elif dt:
        parts.append(f"до {_humanize_iso_date(dt)}")

    if filters.get("city"):
        parts.append(f"город {CITY_LABELS.get(filters['city']) or city_label(filters['city'])}")
    if filters.get("event_type"):
        parts.append(f"тип «{filters['event_type']}»")
    if filters.get("format"):
        parts.append(f"формат {FORMAT_LABELS.get(filters['format']) or format_label(filters['format'])}")
    topics = filters.get("topics") or []
    if topics:
        topic_names = ", ".join(TOPIC_LABELS.get(t) or topic_title(t) for t in topics)
        parts.append(f"темы: {topic_names}")

    if not parts:
        return ""
    return f"🔎 <i>Понял как:</i> {esc(' · '.join(parts))}\n\n"


async def _do_search(message: Message, query: str) -> None:
    query = query.strip()
    if not query:
        await send(message, "Пустой запрос. Напиши, например: <code>конференции по AI в июне в Москве</code>")
        return

    # Продлеваем waiting на каждый успешно начавшийся поиск — пока человек
    # активно ищет, режим не должен истечь по TTL.
    _touch_waiting(message.from_user.id)
    result = await api_client.nl_search(query=query, limit=5)
    events = result.get("events") or []
    extracted = bool(result.get("extracted"))
    relaxed = bool(result.get("relaxed"))
    dropped = result.get("dropped") or []
    original_filters = result.get("original_filters") or {}
    hint = _format_filters_hint(original_filters) if extracted else ""

    # Совсем пусто — пользователь упёрся в стену. Показываем CTA «к рекомендациям».
    if not events:
        relax_note = ""
        if relaxed and dropped:
            relax_note = f"\nДаже без {esc(', '.join(dropped))} ничего."
        await send(
            message,
            f"{hint}По запросу «<b>{esc(query)}</b>» ничего не нашлось.{relax_note}\n\n"
            f"Если поиск даёт ноль — заходи в персональные рекомендации, "
            f"там события подобраны под профиль:",
            reply_markup=_recommendations_cta_keyboard(),
        )
        return

    # Строгий хит — показываем что нашли (до 5).
    if not relaxed:
        intro = f"{hint}По запросу «<b>{esc(query)}</b>» найдено {len(events)}:\n"
        await send(message, intro)
        last_idx = len(events) - 1
        for i, event in enumerate(events):
            if i == last_idx:
                builder = InlineKeyboardBuilder()
                builder.button(text="⭐ Сохранить", callback_data=f"search_save:{event['event_id']}")
                builder.button(text="🔍 Новый поиск", callback_data="search_new")
                builder.adjust(2)
                markup = builder.as_markup()
            else:
                markup = _save_keyboard(event["event_id"])
            await send(message, _format_event_line(event), reply_markup=markup)
        return

    # Relax-fallback — строгого нет, показываем ОДНО ближайшее + CTA «к рекомендациям».
    # «Лучше одно подходящее с честной пометкой, чем 8 случайных» — такой контракт.
    note = (
        f"{hint}⚠️ <i>Точных совпадений нет</i> "
        f"(сняли: {esc(', '.join(dropped))}). Самое близкое:"
    )
    await send(message, note)
    event = events[0]
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Сохранить", callback_data=f"search_save:{event['event_id']}")
    builder.adjust(1)
    await send(message, _format_event_line(event), reply_markup=builder.as_markup())
    await send(
        message,
        "Больше похожих ищи в персональных рекомендациях — там подбор по профилю:",
        reply_markup=_recommendations_cta_keyboard(),
    )


@router.callback_query(F.data.startswith("search_save:"))
async def cb_search_save(callback: CallbackQuery):
    """Сохранение события из результатов поиска (#8). То же действие,
    что кнопка ⭐ в карточке рекомендации — пишет Interaction(action='save').
    """
    try:
        event_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    await api_client.save_interaction(
        telegram_id=callback.from_user.id, event_id=event_id, action="save",
    )
    await callback.answer("⭐ Сохранено")


@router.callback_query(F.data == "search_new")
async def cb_search_new(callback: CallbackQuery):
    """Кнопка «🔍 Новый поиск» под последним результатом — продлевает
    waiting и подсказывает, как сформулировать следующий запрос."""
    _touch_waiting(callback.from_user.id)
    await callback.answer("Жду следующий запрос")
    await send(
        callback,
        "🔍 Напиши следующий запрос. Например:\n"
        "<code>митапы по DevOps на следующей неделе</code>\n"
        "<code>хакатоны в спб в июле</code>",
    )


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
    """Reply-кнопка → переключаемся в режим поиска (sticky на 60 мин)."""
    _touch_waiting(message.from_user.id)
    await send(
        message,
        "🔍 <b>Поиск событий</b>\n\n"
        "Напиши запрос обычным языком. После каждого результата можно "
        "сразу писать следующий — режим поиска включён, пока ты не уйдёшь "
        "в другой раздел (но не дольше часа).\n\n"
        "Примеры:\n"
        "• <code>конференции по AI с 3 по 10 июня в Москве</code>\n"
        "• <code>митапы по DevOps на следующей неделе</code>\n"
        "• <code>онлайн вебинары про Kubernetes</code>",
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
    # waiting не сбрасываем (sticky) — _do_search сам продлевает таймштамп.
    await _do_search(message, message.text)
