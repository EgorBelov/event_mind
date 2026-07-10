"""Unit: series_slug (анти-флуд серий)."""
from __future__ import annotations

from eventmind.domain.events.series import compute_series_slug


def test_same_series_different_issues_collapse() -> None:
    a = compute_series_slug("Python MeetUp #14")
    b = compute_series_slug("Python MeetUp #15")
    assert a == b == "python-meetup"


def test_vol_and_year_markers_stripped() -> None:
    assert compute_series_slug("ML Meetup vol.2") == "ml-meetup"
    assert compute_series_slug("DevOps Days 2026") == "devops-days"


def test_city_suffix_disambiguates() -> None:
    moscow = compute_series_slug("DevOps Days", city="moscow")
    berlin = compute_series_slug("DevOps Days", city="berlin")
    assert moscow != berlin
    assert moscow.endswith("--moscow")


def test_none_when_nothing_left() -> None:
    assert compute_series_slug("#15") is None
    assert compute_series_slug("") is None
    assert compute_series_slug(None) is None


def test_translit_cyrillic() -> None:
    slug = compute_series_slug("Питон Митап")
    assert slug is not None
    assert all(ch.isascii() for ch in slug)
