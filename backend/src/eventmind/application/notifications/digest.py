"""Рендер дайджеста рекомендаций в канал-агностичный NotificationMessage."""
from __future__ import annotations

from html import escape

from eventmind.application.ports.notifications import NotificationMessage
from eventmind.application.recommender.use_cases import RecommendationItem


def _line(item: RecommendationItem) -> str:
    bits = [item.title]
    meta = ", ".join(p for p in (item.date, item.city, item.format) if p and p != "unknown")
    if meta:
        bits.append(f"({meta})")
    return " ".join(bits)


def build_digest_message(
    items: list[RecommendationItem], *, unsubscribe_url: str | None
) -> NotificationMessage:
    """Собрать сообщение дайджеста (subject + text + html + payload)."""
    subject = f"EventMind: {len(items)} рекомендаций для вас"

    text_lines = [
        f"• {_line(it)}" + (f"\n  {it.source_url}" if it.source_url else "") for it in items
    ]
    text = "Ваши персональные IT-события:\n\n" + "\n".join(text_lines)
    if unsubscribe_url:
        text += f"\n\n—\nОтписаться: {unsubscribe_url}"

    html_items = "".join(
        f'<li><a href="{escape(it.source_url or "#")}">{escape(it.title)}</a>'
        f'<br><span style="color:#666;font-size:13px">'
        f'{escape(", ".join(p for p in (it.date, it.city, it.format) if p and p != "unknown"))}'
        f"</span></li>"
        for it in items
    )
    unsub = (
        f'<p style="color:#999;font-size:12px">EventMind · '
        f'<a href="{escape(unsubscribe_url)}">отписаться</a></p>'
        if unsubscribe_url
        else ""
    )
    html = (
        '<div style="font-family:system-ui,Arial,sans-serif;color:#222">'
        "<h2>Ваши персональные IT-события</h2>"
        f"<ul>{html_items}</ul><hr>{unsub}</div>"
    )

    event_items: list[dict[str, object]] = [
        {"event_id": it.event_id, "title": it.title, "source_url": it.source_url}
        for it in items
    ]
    return NotificationMessage(
        subject=subject,
        text=text,
        html=html,
        unsubscribe_url=unsubscribe_url,
        items=event_items,
    )
