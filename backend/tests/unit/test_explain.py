"""Unit: «почему рекомендовано» — причины (`explain_match`), вклад компонент
(P1 №11) и use-case `ExplainEvent` (кэш пересказа, деградация без LLM)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from eventmind.application.ports.llm import LLMMessage, LLMResult
from eventmind.application.ports.recommender import UserPrefs
from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.explain import contributions, explain_match
from eventmind.domain.recommender.scoring import EventFeatures, UserContext
from eventmind.domain.recommender.weights import ScoringWeights
from eventmind.interfaces.bot.formatting import render_explain

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _features(**kw: Any) -> EventFeatures:
    base: dict[str, Any] = {
        "id": 1, "topics": ["golang"], "format": "online", "city": "perm",
        "quality_score": 9, "start_at": NOW + timedelta(days=3), "embedding": [1.0, 0.0],
    }
    base.update(kw)
    return EventFeatures(**base)


def test_explain_match_lists_concrete_reasons() -> None:
    user = UserContext(
        topics={"golang"}, topic_weights={"golang": 3}, preferred_format="online",
        city="perm", embedding=[1.0, 0.0],
    )
    reasons = explain_match(user, _features(), now=NOW)
    assert reasons[0].startswith("Темы из ваших интересов")
    assert "Очень близко по смыслу к вашему профилю и оценкам" in reasons
    assert "Подходящий формат: online" in reasons
    assert any(r.startswith("В вашем городе") for r in reasons)
    assert "Высокая информативность (9/10)" in reasons
    assert "Скоро: через 3 дн." in reasons


def test_explain_match_flags_anti_interest_and_cold_start() -> None:
    user = UserContext(topic_weights={"frontend": -6})
    reasons = explain_match(user, _features(topics=["frontend"], quality_score=None,
                                            start_at=None), now=NOW)
    assert reasons[0].startswith("Есть тема из «не интересно»")
    assert "по общей популярности" in reasons[-1]


def test_contributions_shares_sum_to_one_and_keep_sign() -> None:
    parts = contributions({"cosine": 6.0, "rule": -2.0, "quality": 2.0, "hype": 0.0})
    assert [c.component for c in parts] == ["cosine", "quality", "rule"]
    assert sum(c.share for c in parts) == pytest.approx(1.0)
    assert parts[0].label == "смысл" and parts[0].share == pytest.approx(0.6)
    assert parts[-1].value == -2.0
    assert contributions({"cosine": 0.0}) == []


def test_ranker_explain_is_deterministic_and_matches_components() -> None:
    ranker = HybridRanker(ScoringWeights())
    user = UserContext(topics={"golang"}, topic_weights={"golang": 3}, embedding=[1.0, 0.0])
    stats = {"golang": (5.0, 1.0)}
    first = ranker.explain(user, _features(), stats, now=NOW)
    assert first == ranker.explain(user, _features(), stats, now=NOW)
    assert first["bayesian"] == pytest.approx(5.0 / 6.0 * ScoringWeights().bayesian)
    assert first["cosine"] == pytest.approx(ScoringWeights().cosine)
    assert set(first) == {"rule", "cosine", "bayesian", "quality", "hype", "freshness"}


# ── use-case ──────────────────────────────────────────────────────────────────
def _event() -> Event:
    return Event(
        id=1, source="t", title="Go Meetup", description="Доклады про Go " * 80,
        format="online", city="perm", level="any", date="", topics=["golang"],
        embedding=[1.0, 0.0], quality_score=9,
    )


class _Search:
    async def get_event(self, event_id: int) -> Event | None:
        return _event() if event_id == 1 else None


class _Uow:
    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_user_prefs(self, user_id: int) -> UserPrefs:
        return UserPrefs(interests=["golang"], embedding=[1.0, 0.0], city="perm")

    async def load_bayesian_stats(self, user_id: int, *, now: datetime, gamma: float) -> Any:
        return {}


class _LLM:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[list[LLMMessage], dict[str, Any]]] = []

    async def complete(self, messages: Sequence[LLMMessage], **kw: Any) -> LLMResult:
        self.calls.append((list(messages), kw))
        if self.fail:
            raise RuntimeError("down")
        return LLMResult(text="Митап для Go-разработчиков.", provider="fake")


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _use_case(llm: _LLM, cache: _Cache) -> ExplainEvent:
    return ExplainEvent(
        _Search(), _Uow, llm, cache, _Clock(), ScoringWeights()  # type: ignore[arg-type]
    )


async def test_explain_event_caches_summary_and_isolates_event_text() -> None:
    llm, cache = _LLM(), _Cache()
    first = await _use_case(llm, cache).execute(1, user_id=7)
    second = await _use_case(llm, cache).execute(1, user_id=7)
    assert first is not None and second is not None
    assert first.summary == second.summary == "Митап для Go-разработчиков."
    assert len(llm.calls) == 1 and cache.data == {"explain:v1:1": first.summary}
    messages, kwargs = llm.calls[0]
    assert messages[1].content.startswith("<event>") and kwargs["temperature"] == 0.2
    assert first.reasons and first.contributions[0].component == "cosine"


async def test_explain_event_degrades_without_llm_and_skips_reasons_for_anonymous() -> None:
    result = await _use_case(_LLM(fail=True), _Cache()).execute(1, user_id=None)
    assert result is not None
    assert result.summary_source == "description" and result.summary.endswith("…")
    assert result.reasons == [] and result.contributions == []
    assert await _use_case(_LLM(), _Cache()).execute(2, user_id=1) is None


async def test_explain_without_summary_skips_llm() -> None:
    llm = _LLM()
    result = await _use_case(llm, _Cache()).execute(1, user_id=1, with_summary=False)
    assert result is not None and llm.calls == []


def test_bot_render_explain_shows_positive_contributions() -> None:
    text = render_explain(
        {
            "event": {"title": "Go <Meetup>", "date": "2026-11-01"},
            "summary": "Коротко",
            "reasons": ["Темы из ваших интересов: Golang"],
            "contributions": [
                {"label": "смысл", "share": 0.61, "value": 6.1},
                {"label": "темы, формат, город", "share": 0.3, "value": -3.0},
            ],
        }
    )
    assert "Go &lt;Meetup&gt;" in text and "<b>Почему рекомендовано</b>" in text
    assert "Вклад в подбор: смысл 61%" in text and "темы, формат, город" not in text


def test_failing_scorer_degrades_to_zero_instead_of_crashing() -> None:
    """Регрессия: structlog-вызов с kwarg `event=` сам падал TypeError, и сбой
    одной компоненты ронял всю выдачу вместо деградации в 0."""
    broken = UserContext(topics={"golang"}, topic_weights={"golang": "x"})  # type: ignore[dict-item]
    breakdown = HybridRanker().explain(broken, _features(), {}, now=NOW)
    assert breakdown["rule"] == 0.0 and breakdown["cosine"] == 0.0
