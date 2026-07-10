"""Unit: рендер дайджеста + тихие часы."""
from __future__ import annotations

from eventmind.application.notifications.digest import build_digest_message
from eventmind.application.notifications.use_cases import in_quiet_hours
from eventmind.application.recommender.use_cases import RecommendationItem


def _item(i: int) -> RecommendationItem:
    return RecommendationItem(
        event_id=i, title=f"Event {i}", description="d", date="2026-06-16",
        city="moscow", format="offline", event_type="meetup",
        source_url=f"http://e/{i}", score=1.0, topics=["backend"],
    )


def test_build_digest_message() -> None:
    msg = build_digest_message([_item(1), _item(2)], unsubscribe_url="http://u/unsub")
    assert "2 рекомендаций" in msg.subject
    assert "Event 1" in msg.text and "Event 2" in msg.text
    assert "http://u/unsub" in msg.text
    assert "unsub" in msg.html
    assert len(msg.items) == 2
    assert msg.items[0]["event_id"] == 1


def test_build_digest_without_unsubscribe() -> None:
    msg = build_digest_message([_item(1)], unsubscribe_url=None)
    assert "отписаться" not in msg.html.lower()


def test_in_quiet_hours_same_day_range() -> None:
    assert in_quiet_hours(3, 1, 6) is True
    assert in_quiet_hours(7, 1, 6) is False


def test_in_quiet_hours_wraps_midnight() -> None:
    # тихие часы 22..7
    assert in_quiet_hours(23, 22, 7) is True
    assert in_quiet_hours(3, 22, 7) is True
    assert in_quiet_hours(12, 22, 7) is False


def test_in_quiet_hours_none_disabled() -> None:
    assert in_quiet_hours(3, None, None) is False
    assert in_quiet_hours(3, 5, 5) is False
