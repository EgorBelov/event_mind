"""Unit: пост-обработка нормализатора + normalize() с фейковым LLM."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from eventmind.application.ingestion.normalizer import EventNormalizer, postprocess
from eventmind.application.ingestion.schemas import NormalizedEvent
from eventmind.application.ports.llm import LLMMessage


def _ev(**kw: Any) -> NormalizedEvent:
    base: dict[str, Any] = {
        "title": "PyConf",
        "description": "доклады",
        "format": "offline",
        "city": "msk",
        "level": "middle",
        "date": "2026-06-16",
        "topics": ["Backend"],
        "event_type": "conference",
        "seniority": "middle",
        "quality_score": 8,
        "hype_score": 7,
    }
    base.update(kw)
    return NormalizedEvent(**base)


def test_postprocess_canonicalizes_and_validates() -> None:
    r = postprocess(_ev())
    assert r.is_event is True
    assert r.topics == ["backend"]  # slugified
    assert r.city == "moscow"       # msk → moscow
    assert r.format == "offline"
    assert r.start_at is not None and r.start_at.year == 2026


def test_postprocess_enum_out_of_domain_falls_to_default() -> None:
    r = postprocess(_ev(format="zoom", event_type="party", seniority="guru"))
    assert r.format == "unknown"
    assert r.event_type == "unknown"
    assert r.seniority == "any"


def test_postprocess_invalid_date_becomes_empty() -> None:
    assert postprocess(_ev(date="2026-13-45")).date == ""
    assert postprocess(_ev(date="лето 2026")).date == ""
    r = postprocess(_ev(date="2026-06-16T18:00"))
    assert r.date == "2026-06-16"


def test_postprocess_score_clamped() -> None:
    r = postprocess(_ev(quality_score=99, hype_score=0))
    assert r.quality_score == 10
    assert r.hype_score == 1
    assert postprocess(_ev(quality_score=None)).quality_score is None


def test_postprocess_non_it_marked_not_event() -> None:
    assert postprocess(_ev(topics=[])).is_event is False


def test_postprocess_defence_drops_signalless_event() -> None:
    # topics есть, но нет ни даты, ни формата, ни города, ни типа → не событие
    r = postprocess(
        _ev(topics=["backend"], date="", format="unknown", city="unknown", event_type="unknown")
    )
    assert r.is_event is False
    assert r.topics == []


class _FakeLLM:
    def __init__(self, event: NormalizedEvent) -> None:
        self._event = event

    async def complete(self, *a: Any, **k: Any) -> Any:  # pragma: no cover — не используется
        raise NotImplementedError

    async def structured_output(
        self, messages: Sequence[LLMMessage], schema: type, **kw: Any
    ) -> Any:
        assert schema is NormalizedEvent
        assert any(m.role == "system" for m in messages)
        return self._event


async def test_normalizer_normalize_uses_llm_and_postprocesses() -> None:
    normalizer = EventNormalizer(_FakeLLM(_ev(city="piter")))
    result = await normalizer.normalize(
        title="X", raw_description="desc", source_url="http://x"
    )
    assert result.is_event is True
    assert result.city == "spb"  # piter → spb, канонизировано в пост-обработке
