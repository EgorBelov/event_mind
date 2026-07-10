"""Unit: таксономия событий (slug, канонизация города)."""
from __future__ import annotations

import pytest

from eventmind.domain.events.taxonomy import (
    canonicalize_city,
    humanize_code,
    slugify_code,
    topic_title,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("AI / ML", "ai_ml"), ("  Some  Topic ", "some_topic"), ("DevOps", "devops"), ("", "")],
)
def test_slugify_code(raw: str, expected: str) -> None:
    assert slugify_code(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("msk", "moscow"),
        ("Москва", "москва"),  # кириллица не в алиасах → как есть (slugified)
        ("piter", "spb"),
        ("saint_petersburg", "spb"),
        ("yekaterinburg", "ekb"),
        ("omsk", "omsk"),  # open-domain, остаётся
        ("MSK", "moscow"),  # регистр
    ],
)
def test_canonicalize_city(raw: str, expected: str) -> None:
    assert canonicalize_city(raw) == expected


def test_humanize_and_topic_title() -> None:
    assert humanize_code("nizhny_novgorod") == "Nizhny Novgorod"
    assert topic_title("ai_ml") == "AI / ML"
    assert topic_title("mlops") == "Mlops"  # fallback humanize
