"""Unit: HybridRanker — взвешивание, порядок, anti-flood, детерминизм."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.recommender.scoring import EventFeatures, UserContext

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _rng() -> random.Random:
    return random.Random(42)


def test_higher_quality_and_cosine_ranks_first() -> None:
    user = UserContext(embedding=[1.0, 0.0])
    events = [
        EventFeatures(id=1, embedding=[1.0, 0.0], quality_score=9, start_at=NOW),
        EventFeatures(id=2, embedding=[0.0, 1.0], quality_score=2, start_at=NOW),
    ]
    ranked = HybridRanker().rank(user, events, {}, now=NOW, rng=_rng())
    assert ranked[0].event_id == 1
    assert ranked[0].score > ranked[1].score
    # breakdown содержит все компоненты
    assert set(ranked[0].breakdown) == {
        "rule", "cosine", "bayesian", "quality", "hype", "freshness"
    }


def test_empty_events_returns_empty() -> None:
    assert HybridRanker().rank(UserContext(), [], {}, now=NOW, rng=_rng()) == []


def test_deterministic_with_seeded_rng() -> None:
    user = UserContext(embedding=[1.0, 0.0])
    events = [
        EventFeatures(id=i, embedding=[1.0, 0.0], topics=["backend"], quality_score=5, start_at=NOW)
        for i in range(1, 6)
    ]
    stats = {"backend": (10.0, 1.0)}
    a = HybridRanker().rank(user, events, stats, now=NOW, rng=random.Random(1))
    b = HybridRanker().rank(user, events, stats, now=NOW, rng=random.Random(1))
    assert [x.event_id for x in a] == [x.event_id for x in b]


def test_series_anti_flood_applied_in_ranking() -> None:
    user = UserContext(embedding=[1.0, 0.0])
    events = [
        EventFeatures(id=1, embedding=[1.0, 0.0], series_slug="py",
                      start_at=NOW + timedelta(days=40), quality_score=9),
        EventFeatures(id=2, embedding=[1.0, 0.0], series_slug="py",
                      start_at=NOW + timedelta(days=2), quality_score=3),
    ]
    ranked = HybridRanker().rank(user, events, {}, now=NOW, rng=_rng())
    ids = [r.event_id for r in ranked]
    # из серии остаётся один выпуск (ближайший к now)
    assert ids == [2]


def test_limit_respected() -> None:
    user = UserContext(embedding=[1.0, 0.0])
    events = [EventFeatures(id=i, embedding=[1.0, 0.0], start_at=NOW) for i in range(1, 11)]
    ranked = HybridRanker().rank(user, events, {}, now=NOW, limit=3, rng=_rng())
    assert len(ranked) == 3
