"""aiogram-хендлеры бота. Вся логика — через `BotApiClient` (HTTP к API).

Бот — самостоятельный интерфейс (B1–B5):
- `/start` создаёт аккаунт прямо в Telegram и ведёт онбординг: «о себе» →
  формат → город; `/start <token>` — привязка веб-аккаунта (аккаунт из бота
  при этом сливается в веб-аккаунт на бэкенде);
- `/feed` — лента порциями по 5 + «Ещё ▶» (без повторов, см. `next_feed_page`);
- свободный текст вне диалога — диалоговый агент (A4): сам ищет, подбирает,
  объясняет и предлагает правки профиля (кнопки «Да / Нет»); если агент
  недоступен — прямой NL-поиск. `/search` — всегда прямой поиск без агента;
  `/reset` — начать разговор с агентом заново;
- `/saved`, `/settings` — сохранённое и настройки; «📖 Подробнее» — пересказ +
  почему рекомендовано.

Chat_id берём из `message.chat.id` (в приватном чате = пользователь). Состояние
диалога (онбординг, показанное в ленте) — в FSM-хранилище aiogram (Redis).
"""
from __future__ import annotations

from typing import Any

import structlog
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from eventmind.interfaces.bot.api_client import BotApiClient
from eventmind.interfaces.bot.formatting import (
    esc,
    next_feed_page,
    render_agent_text,
    render_event_card,
    render_explain,
    render_profile,
    render_settings,
)
from eventmind.interfaces.bot.keyboards import (
    DIGEST_NEXT,
    QUIET_DEFAULT,
    agent_confirm_keyboard,
    city_keyboard,
    feed_more_keyboard,
    feedback_keyboard,
    format_keyboard,
    saved_item_keyboard,
    saved_more_keyboard,
    settings_keyboard,
    skip_about_keyboard,
)
from eventmind.interfaces.bot.telegram import send

_logger = structlog.get_logger("eventmind.bot")
router = Router(name="eventmind")

FEED_PAGE = 5
FEED_FETCH = 20  # = RecommenderConfig.result_limit: вся текущая выдача
SAVED_PAGE = 5
_FEED_SHOWN_KEY = "feed_shown"

_HELP = (
    "Я — бот EventMind: подбираю IT-мероприятия под вас и учусь на ваших оценках.\n\n"
    "Просто напишите, что ищете или что вам интересно: «что есть по Go на "
    "выходных?», «почему второе?», «фронтенд мне больше не интересен».\n\n"
    "• /feed — лента рекомендаций\n"
    "• /search &lt;запрос&gt; — прямой поиск обычной фразой\n"
    "• /saved — сохранённое\n"
    "• /settings — о себе, город, формат, дайджест\n"
    "• /reset — начать разговор заново\n\n"
    "Есть аккаунт на сайте? «Настройки → Привязка Telegram» — история из бота "
    "перенесётся в него."
)

_ASK_ABOUT = (
    "Расскажите о себе парой фраз: чем занимаетесь, что интересно, чего не хотите "
    "видеть. Например: <i>«backend на Go, 3 года, хочу в ML, фронтенд не "
    "интересен»</i>.\n\nПо этому тексту я сразу подберу события — ещё до первых оценок."
)

_SERVICE_DOWN = "Сервис временно недоступен, попробуйте чуть позже."


class Onboarding(StatesGroup):
    about = State()
    format = State()
    city = State()
    city_text = State()


class Editing(StatesGroup):
    about = State()
    city_text = State()


def _chat_id(event: Message | CallbackQuery) -> str | None:
    message = event if isinstance(event, Message) else event.message
    if not isinstance(message, Message):
        return None
    return str(message.chat.id)


async def _ensure_account(api: BotApiClient, chat_id: str) -> bool:
    """Гарантировать аккаунт для chat_id (идемпотентно). False — сервис недоступен."""
    return await api.register(chat_id) is not None


# ── /start: регистрация + онбординг (B1/B2) ───────────────────────────────────
@router.message(CommandStart(deep_link=True))
async def start_with_token(
    message: Message, command: CommandObject, api: BotApiClient, state: FSMContext
) -> None:
    chat_id = _chat_id(message)
    token = (command.args or "").strip()
    if not chat_id or not token:
        await start(message, api, state)
        return
    ok, detail = await api.confirm_link(token, chat_id)
    if ok:
        await state.clear()
        await send(message, f"✅ {esc(detail)}\n\nОткройте /feed — покажу рекомендации.")
    else:
        await send(message, f"⚠️ {esc(detail)}")


@router.message(CommandStart())
async def start(message: Message, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    created = await api.register(chat_id)
    if created is None:
        await send(message, _SERVICE_DOWN)
        return
    profile = await api.get_profile(chat_id)
    if created or profile is None or profile.get("is_empty"):
        await state.set_state(Onboarding.about)
        await send(message, "👋 Привет! Я — EventMind.")
        await send(message, _ASK_ABOUT, reply_markup=skip_about_keyboard())
        return
    await state.clear()
    await send(message, _HELP)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await send(message, _HELP)


@router.message(StateFilter(Onboarding.about, Editing.about), F.text & ~F.text.startswith("/"))
async def about_received(message: Message, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    onboarding = await state.get_state() == Onboarding.about.state
    await send(message, "⏳ Разбираю, что вам интересно…")
    profile = await api.save_profile(chat_id, (message.text or "").strip())
    if profile is None:
        await send(message, "Не получилось сохранить — попробуйте ещё раз чуть позже.")
        return
    await send(message, render_profile(profile))
    if onboarding:
        await state.set_state(Onboarding.format)
        await send(message, "Какой формат мероприятий удобнее?", reply_markup=format_keyboard())
    else:
        await state.clear()
        await send(message, "Готово — лента пересчитана: /feed")


@router.callback_query(F.data == "onb:skip")
async def onboarding_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.format)
    await send(
        callback, "Хорошо. Какой формат мероприятий удобнее?", reply_markup=format_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^fmt:(online|offline|hybrid)?$"))
async def format_chosen(callback: CallbackQuery, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    fmt = (callback.data or "").partition(":")[2]
    if await api.update_settings(chat_id, preferred_format=fmt) is None:
        await callback.answer(_SERVICE_DOWN, show_alert=True)
        return
    await callback.answer("Сохранено")
    if await state.get_state() == Onboarding.format.state:
        await state.set_state(Onboarding.city)
        await send(callback, "Из какого вы города?", reply_markup=city_keyboard())


@router.callback_query(F.data.startswith("city:"))
async def city_chosen(callback: CallbackQuery, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    city = (callback.data or "").partition(":")[2]
    onboarding = await state.get_state() in (Onboarding.city.state, Onboarding.format.state)
    if city == "other":
        await state.set_state(Onboarding.city_text if onboarding else Editing.city_text)
        await send(callback, "Напишите название города.")
        await callback.answer()
        return
    if await api.update_settings(chat_id, city=city) is None:
        await callback.answer(_SERVICE_DOWN, show_alert=True)
        return
    await callback.answer("Сохранено")
    if onboarding:
        await _finish_onboarding(callback, api, state)


@router.message(
    StateFilter(Onboarding.city_text, Editing.city_text), F.text & ~F.text.startswith("/")
)
async def city_typed(message: Message, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    onboarding = await state.get_state() == Onboarding.city_text.state
    settings = await api.update_settings(chat_id, city=(message.text or "").strip())
    if settings is None:
        await send(message, _SERVICE_DOWN)
        return
    await send(message, f"📍 Город: {esc(settings.get('city') or 'не важно')}")
    if onboarding:
        await _finish_onboarding(message, api, state)
    else:
        await state.clear()


async def _finish_onboarding(
    target: Message | CallbackQuery, api: BotApiClient, state: FSMContext
) -> None:
    await state.clear()
    await send(target, "Готово! Вот что я подобрал. Оценивайте — я буду точнее.")
    await _show_feed(target, api, state, reset=True)


# ── /feed: лента порциями (B4) ────────────────────────────────────────────────
@router.message(Command("feed"))
async def feed(message: Message, api: BotApiClient, state: FSMContext) -> None:
    await _show_feed(message, api, state, reset=True)


@router.callback_query(F.data == "feed:more")
async def feed_more(callback: CallbackQuery, api: BotApiClient, state: FSMContext) -> None:
    await callback.answer()
    await _show_feed(callback, api, state, reset=False)


async def _show_feed(
    target: Message | CallbackQuery, api: BotApiClient, state: FSMContext, *, reset: bool
) -> None:
    chat_id = _chat_id(target)
    if chat_id is None:
        return
    items = await api.recommendations(chat_id)
    # аккаунта ещё нет (оценки/лента до /start) — создаём и пробуем снова
    if not items and not await api.status(chat_id) and await _ensure_account(api, chat_id):
        items = await api.recommendations(chat_id)
    data = await state.get_data()
    shown: set[int] = set() if reset else set(data.get(_FEED_SHOWN_KEY, []))
    page, remaining = next_feed_page(items, shown, FEED_PAGE)
    if not page:
        await send(
            target,
            "Пока нечего показать — загляните позже или уточните интересы в /settings."
            if reset
            else "Это всё на сейчас 👌 Новые события подтягиваются несколько раз в день.",
        )
        return
    for it in page:
        await send(
            target,
            render_event_card(it, score=_as_float(it.get("score"))),
            reply_markup=feedback_keyboard(int(it["event_id"]), it.get("source_url")),
        )
    shown.update(int(it["event_id"]) for it in page)
    await state.update_data({_FEED_SHOWN_KEY: sorted(shown)})
    if remaining:
        await send(target, f"Ещё {remaining} в ленте.", reply_markup=feed_more_keyboard())
    else:
        await send(target, "Это всё на сейчас 👌")


# ── поиск (B5: оценки под результатами) ───────────────────────────────────────
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
            reply_markup=feedback_keyboard(int(ev["id"]), ev.get("source_url")),
        )


# ── оценки и «📖 Подробнее» (B3/B5) ───────────────────────────────────────────
@router.callback_query(F.data.regexp(r"^(like|save|hide):\d+$"))
async def on_feedback(callback: CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(callback)
    data = callback.data or ""
    action, _, raw_id = data.partition(":")
    api_action = {"like": "like", "save": "save", "hide": "dislike"}[action]
    ok = False
    if chat_id is not None:
        ok = await api.interact(chat_id, int(raw_id), api_action)
        if not ok and await _ensure_account(api, chat_id):
            # оценка из поиска до /start — аккаунт создаём на лету и повторяем
            ok = await api.interact(chat_id, int(raw_id), api_action)
    labels = {"like": "👍 учтено", "save": "⭐ сохранено", "hide": "👎 больше не покажу"}
    await callback.answer(labels[action] if ok else _SERVICE_DOWN, show_alert=not ok)


@router.callback_query(F.data.regexp(r"^more:\d+$"))
async def on_more(callback: CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    _, _, raw_id = (callback.data or "").partition(":")
    await callback.answer("Готовлю описание…")
    explanation = await api.explain(chat_id, int(raw_id))
    if explanation is None:
        await send(callback, "Не удалось получить описание — попробуйте позже.")
        return
    event = explanation.get("event") or {}
    await send(
        callback,
        render_explain(explanation),
        reply_markup=feedback_keyboard(int(raw_id), event.get("source_url")),
    )


# ── /saved (B2) ───────────────────────────────────────────────────────────────
@router.message(Command("saved"))
async def saved_cmd(message: Message, api: BotApiClient) -> None:
    await _show_saved(message, api, offset=0)


@router.callback_query(F.data.regexp(r"^saved:\d+$"))
async def saved_more(callback: CallbackQuery, api: BotApiClient) -> None:
    await callback.answer()
    await _show_saved(callback, api, offset=int((callback.data or "0").partition(":")[2]))


async def _show_saved(target: Message | CallbackQuery, api: BotApiClient, *, offset: int) -> None:
    chat_id = _chat_id(target)
    if chat_id is None:
        return
    page = await api.saved(chat_id, offset=offset, limit=SAVED_PAGE)
    items = page.get("items") or []
    total = int(page.get("total") or 0)
    if not items:
        await send(
            target,
            "В сохранённом пусто — жмите ⭐ под карточками." if offset == 0 else "Это всё.",
        )
        return
    if offset == 0:
        await send(target, f"⭐ Сохранено: {total}")
    for ev in items:
        await send(
            target,
            render_event_card(ev),
            reply_markup=saved_item_keyboard(int(ev["id"]), ev.get("source_url")),
        )
    next_offset = offset + len(items)
    if next_offset < total:
        await send(
            target,
            f"Показано {next_offset} из {total}.",
            reply_markup=saved_more_keyboard(next_offset),
        )


@router.callback_query(F.data.regexp(r"^unsave:\d+$"))
async def on_unsave(callback: CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    event_id = int((callback.data or "").partition(":")[2])
    ok = await api.remove_saved(chat_id, event_id)
    await callback.answer("🗑 Убрано" if ok else "Уже убрано или сервис недоступен")
    if ok and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


# ── /settings (B2) ────────────────────────────────────────────────────────────
@router.message(Command("settings"))
async def settings_cmd(message: Message, api: BotApiClient, state: FSMContext) -> None:
    await state.clear()
    await _show_settings(message, api)


async def _show_settings(target: Message | CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(target)
    if chat_id is None:
        return
    settings = await api.get_settings(chat_id)
    if settings is None and await _ensure_account(api, chat_id):
        settings = await api.get_settings(chat_id)
    if settings is None:
        await send(target, _SERVICE_DOWN)
        return
    profile = await api.get_profile(chat_id)
    await send(
        target,
        render_settings(settings, profile),
        reply_markup=settings_keyboard(
            str(settings.get("digest_frequency")), settings.get("quiet_hours_start") is not None
        ),
    )


@router.callback_query(F.data.startswith("set:"))
async def settings_action(callback: CallbackQuery, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    action = (callback.data or "").partition(":")[2]
    await callback.answer()
    if action == "about":
        await state.set_state(Editing.about)
        await send(callback, _ASK_ABOUT)
    elif action == "city":
        await state.clear()
        await send(callback, "Выберите город:", reply_markup=city_keyboard())
    elif action == "fmt":
        await state.clear()
        await send(callback, "Какой формат удобнее?", reply_markup=format_keyboard())
    elif action == "saved":
        await _show_saved(callback, api, offset=0)
    elif action in ("digest", "quiet"):
        current = await api.get_settings(chat_id)
        if current is None:
            await send(callback, _SERVICE_DOWN)
            return
        update: dict[str, Any]
        if action == "digest":
            frequency = str(current["digest_frequency"])
            update = {"digest_frequency": DIGEST_NEXT.get(frequency, "daily")}
        elif current.get("quiet_hours_start") is not None:
            update = {"clear_quiet_hours": True}
        else:
            update = {"quiet_hours_start": QUIET_DEFAULT[0], "quiet_hours_end": QUIET_DEFAULT[1]}
        if await api.update_settings(chat_id, **update) is None:
            await send(callback, _SERVICE_DOWN)
            return
        await _show_settings(callback, api)


# ── свободный текст вне диалога = агент (A4) ──────────────────────────────────
@router.message(Command("reset"))
async def reset_cmd(message: Message, api: BotApiClient, state: FSMContext) -> None:
    chat_id = _chat_id(message)
    if chat_id is None:
        return
    await state.clear()
    await api.agent_reset(chat_id)
    await send(message, "Начнём заново. Что ищете — тема, город, даты?")


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def freeform(message: Message, api: BotApiClient) -> None:
    chat_id = _chat_id(message)
    text = (message.text or "").strip()
    if chat_id is None or not text:
        return
    await _typing(message)
    reply = await api.agent_message(chat_id, text)
    if reply is None and not await api.status(chat_id) and await _ensure_account(api, chat_id):
        # аккаунта ещё нет — создаём на лету и повторяем
        reply = await api.agent_message(chat_id, text)
    if reply is None or reply.get("degraded"):
        await _run_search(message, text, api)  # агент недоступен — прямой поиск
        return
    await _show_agent_reply(message, reply)


@router.callback_query(F.data.regexp(r"^agent:(yes|no):[0-9a-f]{1,40}$"))
async def on_agent_confirm(callback: CallbackQuery, api: BotApiClient) -> None:
    chat_id = _chat_id(callback)
    if chat_id is None:
        return
    _, decision, action_id = (callback.data or "").split(":", 2)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    reply = await api.agent_confirm(chat_id, action_id, approve=decision == "yes")
    if reply is None:
        await send(callback, _SERVICE_DOWN)
        return
    await _show_agent_reply(callback, reply)


async def _show_agent_reply(target: Message | CallbackQuery, reply: dict[str, Any]) -> None:
    pending = reply.get("pending")
    await send(
        target,
        render_agent_text(reply),
        reply_markup=agent_confirm_keyboard(str(pending["id"])) if pending else None,
    )
    for ev in reply.get("events") or []:
        await send(
            target,
            render_event_card(ev),
            reply_markup=feedback_keyboard(int(ev["id"]), ev.get("source_url")),
        )


async def _typing(message: Message) -> None:
    if message.bot is None:
        return
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception as exc:  # индикатор — косметика
        _logger.debug("typing_failed", error=str(exc))


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
