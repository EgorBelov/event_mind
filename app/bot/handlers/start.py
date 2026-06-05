import contextlib
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.inline import (
    CITY_LABELS,
    FORMAT_LABELS,
    TOPIC_LABELS,
    city_keyboard,
    format_keyboard,
    topics_keyboard,
    tour_keyboard,
)
from app.bot.keyboards.reply import main_menu_keyboard
from app.bot.services.api_client import EventMindAPIClient

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
        "<b>/recommend</b> или кнопка «🎯 Рекомендации» — лента событий, "
        "отсортированных под тебя hybrid-скорингом по 9 компонентам "
        "(темы, смысл, история, скиллы и др.).\n\n"
        "В каждой карточке: 📖 Подробнее / 👍 / 👎 / ⭐ / Похожие / Следующее.\n"
        "«📖 Подробнее» — простое человеческое описание события от ИИ "
        "(что это, для кого, о чём).",
    ),
    (
        "🔍 Шаг 2/4 — Поиск",
        "Нажми кнопку «🔍 Поиск» и напиши, что искать — обычным языком.\n\n"
        "ИИ сам выдернет даты, город и тип события:\n"
        "• <code>конференции по AI с 3 по 10 июня в Москве</code>\n"
        "• <code>митапы по DevOps на следующей неделе</code>\n"
        "• <code>хочу научиться деплоить микросервисы</code>\n\n"
        "Под каждым результатом — кнопка ⭐ «Сохранить».",
    ),
    (
        "🔥 Шаг 3/4 — Тренды и дайджест",
        "<b>/trending</b> — горячие темы за неделю с ASCII-графиком.\n"
        "<b>/subscribe</b> — ежедневный AI-дайджест в личку.\n\n"
        "В разделе «⚙️ Ещё» собраны тренды и помощь по командам.",
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
                from app.bot.utils import event_url_line, format_event_date
                text = (
                    f"<b>{event.get('title', '')}</b>\n\n"
                    f"📅 {format_event_date(event)}\n"
                    f"📍 {event.get('city', '')} · {event.get('format', '')}"
                    f"{event_url_line(event)}\n\n"
                    f"{(event.get('description') or '')[:600]}"
                )
                await message.answer(text, parse_mode="HTML", disable_web_page_preview=False)
                return
    # Неизвестный payload — обычный приветственный экран.
    await _greet(message)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await _greet(message)


async def _greet(message: Message) -> None:
    user_setup_state[message.from_user.id] = SetupState()

    # На старте принудительно сбрасываем persistent reply-клавиатуру:
    # у старых пользователей мог остаться setup_keyboard() из прошлой
    # версии с кнопкой «Начать настройку», которая дублировала инлайн-кнопку
    # в туре. ReplyKeyboardRemove форсирует Telegram её снять.
    from aiogram.types import ReplyKeyboardRemove
    await message.answer(
        "Привет! Я <b>EventMind</b> — бот для подбора IT-событий по твоим интересам.\n\n"
        "Я могу:\n"
        "- подобрать мероприятия по темам и формату;\n"
        "- показать наиболее подходящие события;\n"
        "- учитывать твои предпочтения для персональных рекомендаций.\n\n"
        "Сейчас покажу короткий тур (4 экрана), а в конце предложу настроить профиль.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Краткий тур по командам — 4 экрана с инлайн-навигацией. В конце —
    # кнопка «🚀 Начать настройку» в самом туре.
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
        # Даже при пропуске тура нужна точка входа в настройку профиля —
        # иначе у пользователя остаётся только reply-меню без кнопки запуска.
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="🚀 Начать настройку", callback_data="start_setup")
        builder.adjust(1)
        await callback.message.answer(
            "Окей, тур пропущен.\n\n"
            "Чтобы я начал подбирать события, настрой профиль — это 3 коротких шага: "
            "темы, формат, город.",
            reply_markup=builder.as_markup(),
        )
        return
    try:
        step = int(payload)
    except ValueError:
        await callback.answer()
        return
    step = max(1, min(step, len(_TOUR_PAGES)))
    await callback.answer()
    await _send_tour(callback, step)




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

    # Тур завершён — убираем сообщение с навигацией тура (иначе кнопка
    # «Пропустить тур» висит уже после старта настройки и сбивает с толку).
    with contextlib.suppress(Exception):
        await callback.message.delete()

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
        f"Готово! Нажми «🎯 Рекомендации» в меню внизу, чтобы посмотреть подборку.",
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