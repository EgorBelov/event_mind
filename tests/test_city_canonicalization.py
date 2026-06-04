"""Тесты канонизации города: алиасы (msk/piter/yekaterinburg/...) схлопываются
к каноническим slug-ам, расширенный seed-словарь отдаёт русские лейблы,
постпроцессинг нормализатора применяет канонизацию до сохранения.
"""
import pytest

from app.agents.event_normalization.agent import _postprocess_normalized
from app.core.topics import (
    CANONICAL_CITIES,
    CITY_ALIASES,
    SEED_CITY_LABELS,
    canonicalize_city,
    city_label,
)


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("msk", "moscow"),
        ("moskva", "moscow"),
        ("moscow_city", "moscow"),
        ("MSK", "moscow"),
        ("saint_petersburg", "spb"),
        ("sankt_peterburg", "spb"),
        ("piter", "spb"),
        ("leningrad", "spb"),
        ("ekaterinburg", "ekb"),
        ("yekaterinburg", "ekb"),
        ("yekb", "ekb"),
        ("nsk", "novosibirsk"),
        ("nn", "nizhny_novgorod"),
        ("nizhniy_novgorod", "nizhny_novgorod"),
        ("rostov_on_don", "rostov"),
        ("rostov_na_donu", "rostov"),
        ("chel", "chelyabinsk"),
    ],
)
def test_canonicalize_collapses_aliases(alias, canonical):
    assert canonicalize_city(alias) == canonical


@pytest.mark.parametrize("canon", ["moscow", "spb", "kazan", "ekb", "novosibirsk"])
def test_canonicalize_keeps_canonical_unchanged(canon):
    assert canonicalize_city(canon) == canon


@pytest.mark.parametrize("special", ["any", "unknown"])
def test_canonicalize_passes_special_values(special):
    assert canonicalize_city(special) == special


def test_canonicalize_unknown_slug_returns_as_is():
    # «Экзотика» — slug города, которого нет ни в seed, ни в aliases.
    # Не должен превращаться в "unknown"; должен идти как есть, чтобы
    # SELECT DISTINCT в /vocabulary/cities его подхватил.
    assert canonicalize_city("omsk") == "omsk"
    assert canonicalize_city("barnaul") == "barnaul"


def test_canonicalize_empty_inputs():
    assert canonicalize_city("") == ""
    assert canonicalize_city(None) == ""


def test_alias_map_targets_only_canonical_cities():
    """Каждый алиас должен ссылаться на slug из CANONICAL_CITIES — иначе
    канонизация ведёт в never-land, и в БД попадает несуществующий slug."""
    for alias, target in CITY_ALIASES.items():
        assert target in CANONICAL_CITIES, (
            f"alias {alias!r} → {target!r}: target not in canonical set"
        )
        # Алиас не должен совпадать с каноническим slug-ом — это просто
        # шум в таблице.
        assert alias != target


def test_expanded_seed_has_russian_labels():
    """Новые seed-города возвращают именно русское название, не Title-Case
    fallback из humanize_code."""
    for canon in ("novosibirsk", "nizhny_novgorod", "chelyabinsk",
                  "samara", "ufa", "rostov", "krasnodar", "voronezh",
                  "perm", "tomsk", "innopolis", "sochi", "vladivostok"):
        assert canon in SEED_CITY_LABELS
        label = city_label(canon)
        # Базовый smoke-check: лейбл не пустой и не латинский Title-Case
        # из humanize_code (тот бы дал, например, "Novosibirsk").
        assert label
        assert any("Ѐ" <= ch <= "ӿ" for ch in label), (
            f"city_label({canon!r}) = {label!r}: expected Cyrillic label"
        )


def test_postprocess_canonicalizes_msk_to_moscow():
    """Интеграция: LLM эмитнул `msk` — на выходе должно быть `moscow`."""
    raw = {
        "title": "Test", "description": "x", "topics": ["ai_ml"],
        "format": "offline", "city": "msk", "level": "middle",
        "seniority": "any", "event_type": "meetup",
        "date": "2026-06-01", "tech_stack": [], "quality_score": 7, "hype_score": 8,
    }
    out = _postprocess_normalized(raw)
    assert out["city"] == "moscow"


def test_postprocess_canonicalizes_piter_to_spb():
    raw = {
        "title": "T", "description": "x", "topics": ["devops"],
        "format": "offline", "city": "Piter", "level": "any",
        "seniority": "any", "event_type": "meetup",
        "date": "2026-06-01", "tech_stack": [], "quality_score": 5, "hype_score": 5,
    }
    out = _postprocess_normalized(raw)
    assert out["city"] == "spb"


def test_postprocess_passes_unknown_city_through():
    """Экзотика проходит без изменений — open-domain словарь растёт."""
    raw = {
        "title": "T", "description": "x", "topics": ["backend"],
        "format": "offline", "city": "Omsk", "level": "any",
        "seniority": "any", "event_type": "meetup",
        "date": "2026-06-01", "tech_stack": [], "quality_score": 5, "hype_score": 5,
    }
    out = _postprocess_normalized(raw)
    assert out["city"] == "omsk"
