"""Чистые хелперы рендеринга карточек для бота (без aiogram — тестируемо).

Портирует локализацию дат и ссылку на источник из `legacy/app/bot/utils.py`,
но работает с dict'ами, которые бот получает от API (`EventDetailResponse`/
`RecommendationResponse`).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_DEFAULT_TZ = ZoneInfo("Europe/Moscow")
_MONTHS_RU_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def esc(value: Any) -> str:
    """Экранировать произвольное значение под HTML parse_mode Telegram."""
    return html.escape("" if value is None else str(value))


def to_plain(text: str) -> str:
    """HTML → plain: снять теги и развернуть сущности (для fallback)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def format_event_date(event: dict[str, Any], tz: ZoneInfo = _DEFAULT_TZ) -> str:
    """Дата события для карточки.

    Приоритет — `start_at` (ISO от нормализатора) с локализацией в TZ. Если
    время нулевое (источник его не дал — 00:00 UTC), показываем только дату,
    чтобы не выдумывать «03:00 MSK». Иначе — `date` как есть, а голый ISO
    переводим в человеческий вид.
    """
    raw_iso = event.get("start_at")
    if raw_iso:
        try:
            dt = datetime.fromisoformat(str(raw_iso))
            time_known = bool(dt.hour or dt.minute or dt.second)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local = dt.astimezone(tz)
            month = _MONTHS_RU_GEN[local.month - 1]
            if time_known:
                return f"{local.day} {month} {local.year}, {local:%H:%M} {tz.key.split('/')[-1]}"
            return f"{local.day} {month} {local.year}"
        except (ValueError, TypeError):
            pass

    raw_date = str(event.get("date") or "").strip()
    if not raw_date:
        return "—"
    try:
        d = datetime.fromisoformat(raw_date).date()
        return f"{d.day} {_MONTHS_RU_GEN[d.month - 1]} {d.year}"
    except ValueError:
        return raw_date


def event_url_line(event: dict[str, Any], label: str = "🔗 Открыть на источнике") -> str:
    """HTML-строка со ссылкой на источник, либо пустая. href экранируется."""
    url = str(event.get("source_url") or "").strip()
    if not url:
        return ""
    return f'\n<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


def render_event_card(event: dict[str, Any], *, score: float | None = None) -> str:
    """Собрать HTML-карточку события для сообщения бота."""
    lines = [f"<b>{esc(event.get('title'))}</b>"]
    meta: list[str] = [f"📅 {esc(format_event_date(event))}"]
    if event.get("city"):
        meta.append(f"📍 {esc(event['city'])}")
    if event.get("format"):
        meta.append(f"💻 {esc(event['format'])}")
    if event.get("event_type"):
        meta.append(f"🏷 {esc(event['event_type'])}")
    lines.append(" · ".join(meta))

    summary = str(event.get("summary") or event.get("description") or "").strip()
    if summary:
        clipped = summary[:400] + ("…" if len(summary) > 400 else "")
        lines.append(esc(clipped))

    topics = event.get("topics") or []
    if isinstance(topics, list) and topics:
        lines.append(" ".join(f"#{esc(t)}" for t in topics[:6]))

    line = event_url_line(event)
    card = "\n".join(lines)
    if score is not None:
        card += f"\n<i>★ {score:.2f}</i>"
    return card + line


# ── профиль, настройки, «Подробнее» (B2/B3) ───────────────────────────────────
_LEVELS = {"junior": "junior", "middle": "middle", "senior": "senior"}
_FORMATS = {"online": "онлайн", "offline": "офлайн", "hybrid": "гибрид"}


def render_profile(profile: dict[str, Any]) -> str:
    """«Как система вас видит» — выжимка профиля «о себе»."""
    if profile.get("is_empty"):
        return "Профиль пока пуст — расскажите о себе: /settings → «✏️ О себе»."
    lines = ["<b>Как я вас понял</b>"]
    if profile.get("role"):
        lines.append(f"👤 {esc(profile['role'])}")
    level = _LEVELS.get(str(profile.get("level") or ""))
    if level:
        lines.append(f"📈 Уровень: {level}")
    for key, label in (
        ("stack", "🧰 Стек"),
        ("interests", "✅ Интересно"),
        ("anti_interests", "🚫 Не интересно"),
        ("goals", "🎯 Цели"),
        ("skill_gaps", "🧭 Не хватает для целей"),
    ):
        values = profile.get(key) or []
        if isinstance(values, list) and values:
            sep = "; " if key == "goals" else ", "
            lines.append(f"{label}: {esc(sep.join(str(v) for v in values))}")
    if not profile.get("has_embedding"):
        lines.append(
            "<i>Семантический профиль пока не построен — подбираю по объявленным интересам.</i>"
        )
    return "\n".join(lines)


def render_settings(settings: dict[str, Any], profile: dict[str, Any] | None) -> str:
    city = settings.get("city") or "не важно"
    fmt = _FORMATS.get(str(settings.get("preferred_format") or ""), "не важно")
    digest = {"daily": "ежедневно", "weekly": "еженедельно", "off": "выключен"}.get(
        str(settings.get("digest_frequency")), str(settings.get("digest_frequency"))
    )
    start, end = settings.get("quiet_hours_start"), settings.get("quiet_hours_end")
    quiet = f"{start}:00–{end:02d}:00" if start is not None and end is not None else "выключены"
    lines = [
        "<b>Настройки</b>",
        f"📍 Город: {esc(city)}",
        f"💻 Формат: {fmt}",
        f"📬 Дайджест: {digest}",
        f"🔕 Тихие часы: {quiet}",
    ]
    if profile is not None:
        about = str(profile.get("about") or "").strip()
        clipped = about[:300] + ("…" if len(about) > 300 else "")
        lines.append(f"✏️ О себе: {esc(clipped) if about else '— не заполнено'}")
    return "\n".join(lines)


def render_explain(explanation: dict[str, Any]) -> str:
    """«📖 Подробнее»: заголовок, пересказ, почему рекомендовано, ссылка."""
    event = explanation.get("event") or {}
    lines = [f"<b>{esc(event.get('title'))}</b>", f"📅 {esc(format_event_date(event))}"]
    summary = str(explanation.get("summary") or "").strip()
    if summary:
        lines.append("")
        lines.append(esc(summary))
    reasons = explanation.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        lines.append("")
        lines.append("<b>Почему рекомендовано</b>")
        lines.extend(f"• {esc(r)}" for r in reasons)
    parts = [
        c for c in explanation.get("contributions") or [] if float(c.get("value", 0)) > 0
    ][:4]
    if parts:
        shares = " · ".join(f"{esc(c['label'])} {float(c['share']):.0%}" for c in parts)
        lines.append(f"<i>Вклад в подбор: {shares}</i>")
    return "\n".join(lines) + event_url_line(event)


def next_feed_page(
    items: list[dict[str, Any]], shown: set[int], page_size: int
) -> tuple[list[dict[str, Any]], int]:
    """Следующая порция ленты без уже показанного: (порция, сколько ещё осталось).

    Оценённое уходит из выдачи (сервер его исключает), поэтому смещение по
    индексу «съезжало» бы — фильтруем по множеству показанных id.
    """
    fresh = [it for it in items if int(it["event_id"]) not in shown]
    return fresh[:page_size], max(0, len(fresh) - page_size)


def render_agent_text(reply: dict[str, Any]) -> str:
    """Текст ответа агента (экранированный). Предложенное изменение уже входит
    в текст — под ним бот ставит кнопки «Да / Нет»."""
    text = str(reply.get("text") or "").strip()
    return esc(text) if text else "Готово."
