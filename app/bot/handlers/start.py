import contextlib
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.inline import (
    CITY_LABELS,
    FORMAT_LABELS,
    TOPIC_LABELS,
    after_setup_keyboard,
    city_keyboard,
    format_keyboard,
    start_keyboard,
    topics_keyboard,
    tour_keyboard,
)
from app.bot.keyboards.reply import main_menu_keyboard, setup_keyboard
from app.bot.services.api_client import EventMindAPIClient
from app.bot.utils import send

router = Router()
api_client = EventMindAPIClient()


@dataclass
class SetupState:
    topics: set[str] = field(default_factory=set)
    preferred_format: str | None = None
    city: str | None = None


user_setup_state: dict[int, SetupState] = {}


def get_state(user_id: int) -> SetupState:
    if user_id not in user_setup_state:
        user_setup_state[user_id] = SetupState()
    return user_setup_state[user_id]


# ─── Тур по командам ─────────────────────────────────────────────────────


_TOUR_PAGES: list[tuple[str, str]] = [
    (
        "🎯 Шаг 1/4 — Персональные рекомендации",
        "<b>/recommend</b> — лента событий, отсортированных под тебя.\n"
        "Нажми «🤖 AI» в пикере, чтобы получить карточки от LangGraph-агентов "
        "с пояснением «почему именно это».\n\n"
        "В каждой карточке: 👍 / 👎 / ⭐ / Похожие / Следующее.",
    ),
    (
        "🔍 Шаг 2/4 — Поиск",
        "<b>/search &lt;запрос&gt;</b> — поиск по тексту: темы, формат, город.\n"
        "<b>/semantic &lt;запрос&gt;</b> — семантический поиск через embeddings: "
        "находит близкие по смыслу события, даже если слова другие.\n\n"
        "Пример: <code>/semantic машинное обучение для бэкендера</code>",
    ),
    (
        "🤖 Шаг 3/4 — AI Copilot и тренды",
        "<b>/copilot &lt;цель&gt;</b> — мультиагентный помощник: roadmap, "
        "анализ карьеры, объяснение событий. Поддерживает многоtuровый диалог.\n\n"
        "<b>/trending</b> — горячие темы за неделю с ASCII-графиком.\n"
        "<b>/subscribe</b> — ежедневный AI-дайджест в личку.",
    ),
    (
        "⚙️ Шаг 4/4 — Профиль и быстрые действия",
        "<b>/profile</b> — текущие интересы и веса.\n"
        "<b>/edit</b> — перенастроить темы/формат/город.\n"
        "<b>/bio &lt;текст&gt;</b> — холодный старт по описанию о себе.\n"
        "<b>/undo</b> — откатить последний лайк/дизлайк/сохранение.\n\n"
        "Готов начать настройку?",
    ),
]


def _tour_text(step: int) -> str:
    title, body = _TOUR_PAGES[step - 1]
    return f"<b>{title}</b>\n\n{body}"


async def _send_tour(message_or_callback, step: int) -> None:
    total = len(_TOUR_PAGES)
    text = _tour_text(step)
    kb = tour_keyboard(step, total)
    if isinstance(message_or_callback, CallbackQuery):
        try:
            await message_or_callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await message_or_callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message_or_callback.answer(text, parse_mode="HTML", reply_markup=kb)


# ─── /start с deep-linking ──────────────────────────────────────────────


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, command: CommandObject):
    """Поддержка t.me/<bot>?start=event_<id> — открывает карточку события.

    Полезно для шеринга: ссылку из веба можно бросить в чат, и пользователь
    попадает сразу на событие, минуя меню.
    """
    payload = (command.args or "").strip()
    if payload.startswith("event_"):
        try:
            event_id = int(payload.split("_", 1)[1])
        except ValueError:
            event_id = None
        if event_id is not None:
            try:
                event = await api_client.get_event(event_id)
            except Exception:
                event = None
            if event:
                text = (
                    f"<b>{event.get('title', '')}</b>\n\n"
                    f"📅 {event.get('date', '')}\n"
                    f"📍 {event.get('city', '')} · {event.get('format', '')}\n\n"
                    f"{(event.get('description') or '')[:600]}"
                )
                if event.get("source_url"):
                    text += f"\n\n<a href=\"{event['source_url']}\">Подробнее</a>"
                await message.answer(text, parse_mode="HTML", disable_web_page_preview=False)
                return
    # Неизвестный payload — обычный приветственный экран.
    await _greet(message)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await _greet(message)


async def _greet(message: Message) -> None:
    user_setup_state[message.from_user.id] = SetupState()

    await send(
        message,
        "Привет! Я <b>EventMind</b> — бот для подбора IT-событий по твоим интересам.\n\n"
        "Я могу:\n"
        "- подобрать мероприятия по темам и формату;\n"
        "- показать наиболее подходящие события;\n"
        "- учитывать твои предпочтения для персональных рекомендаций.\n\n"
        "Давай быстро настроим профиль.",
        reply_markup=setup_keyboard(),
    )

    await message.answer(
        "Также можно использовать inline-кнопки ниже:",
        reply_markup=start_keyboard(),
    )

    # Краткий тур по командам — 4 экрана с инлайн-навигацией.
    await _send_tour(message, step=1)


# ─── Навигация по туру ──────────────────────────────────────────────────


@router.message(Command("tour"))
async def cmd_tour(message: Message):
    await _send_tour(message, step=1)


@router.callback_query(F.data.startswith("tour:"))
async def cb_tour_nav(callback: CallbackQuery):
    payload = callback.data.split(":", 1)[1]
    if payload == "skip":
        await callback.answer("Тур пропущен.")
        with contextlib.suppress(Exception):
            await callback.message.delete()
        return
    try:
        step = int(payload)
    except ValueError:
        await callback.answer()
        return
    step = max(1, min(step, len(_TOUR_PAGES)))
    await callback.answer()
    await _send_tour(callback, step)


@router.callback_query(F.data == "how_it_works")
async def cb_how_it_works(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Я подбираю IT-события на основе твоих интересов.\n\n"
        "Сначала ты указываешь темы, формат и город, а затем я показываю подходящие мероприятия.\n"
        "В дальнейшем рекомендации можно улучшать по твоим действиям."
    )


async def _extra_topic_codes() -> list[str]:
    """Коды, которые есть в БД, но отсутствуют в seed-списке."""
    items = await api_client.get_vocabulary("topics")
    seed = set(TOPIC_LABELS.keys())
    return [item["code"] for item in items if item.get("code") and item["code"] not in seed]


async def _extra_city_codes() -> list[str]:
    items = await api_client.get_vocabulary("cities")
    from app.bot.keyboards.inline import CITY_LABELS as _seed_cities
    seed = set(_seed_cities.keys())
    return [item["code"] for item in items if item.get("code") and item["code"] not in seed]


@router.callback_query(F.data == "start_setup")
async def cb_start_setup(callback: CallbackQuery):
    await callback.answer()
    state = get_state(callback.from_user.id)

    await callback.message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes()),
    )


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic_toggle(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    topic_key = callback.data.split(":", 1)[1]

    if topic_key in state.topics:
        state.topics.remove(topic_key)
    else:
        state.topics.add(topic_key)

    await callback.message.edit_reply_markup(
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes())
    )


@router.callback_query(F.data == "topics_done")
async def cb_topics_done(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)

    if not state.topics:
        await callback.message.answer("Выбери хотя бы одну тему.")
        return

    from app.core.topics import topic_title
    selected_topics = ", ".join(
        TOPIC_LABELS.get(topic) or topic_title(topic) for topic in state.topics
    )

    await callback.message.answer(
        f"Отлично. Я сохранил выбранные темы:\n{selected_topics}\n\n"
        f"Теперь выбери предпочитаемый формат событий.",
        reply_markup=format_keyboard(),
    )


@router.callback_query(F.data.startswith("format:"))
async def cb_format_selected(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    state.preferred_format = callback.data.split(":", 1)[1]

    await callback.message.answer(
        "Укажи город для оффлайн-событий.",
        reply_markup=city_keyboard(extra_codes=await _extra_city_codes()),
    )


@router.callback_query(F.data.startswith("city:"))
async def cb_city_selected(callback: CallbackQuery):
    await callback.answer()

    state = get_state(callback.from_user.id)
    state.city = callback.data.split(":", 1)[1]

    user = callback.from_user

    await api_client.register_user(
        telegram_id=user.id,
        username=user.username,
        preferred_format=state.preferred_format,
        city=state.city,
        topics=list(state.topics),
    )

    from app.core.topics import city_label, format_label, topic_title
    topics_text = ", ".join(
        TOPIC_LABELS.get(topic) or topic_title(topic) for topic in state.topics
    )
    format_text = FORMAT_LABELS.get(state.preferred_format) or format_label(state.preferred_format)
    city_text = CITY_LABELS.get(state.city) or city_label(state.city)

    await callback.message.answer(
        f"Профиль настроен.\n\n"
        f"Я учту:\n"
        f"- темы: {topics_text}\n"
        f"- формат: {format_text}\n"
        f"- город: {city_text}\n\n"
        f"Теперь можно посмотреть рекомендации.",
        reply_markup=after_setup_keyboard(),
    )

    await callback.message.answer(
        "Главное меню обновлено.",
        reply_markup=main_menu_keyboard(),
    )

@router.message(Command("edit"))
async def cmd_edit(message: Message):
    user_setup_state[message.from_user.id] = SetupState()

    await message.answer(
        "Давай обновим профиль.\n\n"
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(set(), extra_codes=await _extra_topic_codes()),
    )

@router.callback_query(F.data == "profile:edit")
async def cb_profile_edit(callback: CallbackQuery):
    await callback.answer()
    user_setup_state[callback.from_user.id] = SetupState()

    await callback.message.answer(
        "Давай обновим профиль.\n\n"
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(set(), extra_codes=await _extra_topic_codes()),
    )


@router.message(F.text == "Начать настройку")
async def msg_start_setup(message: Message):
    state = get_state(message.from_user.id)

    await message.answer(
        "Выбери интересующие темы. Можно выбрать несколько.",
        reply_markup=topics_keyboard(state.topics, extra_codes=await _extra_topic_codes()),
    )