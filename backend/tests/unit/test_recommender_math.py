"""Unit: чистая математика рекомендера (scoring, bayesian, mmr, anti-flood)."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from eventmind.domain.recommender.bayesian import (
    apply_decay,
    feedback_delta,
    posterior_mean,
    thompson_score,
)
from eventmind.domain.recommender.mmr import RankedItem, mmr_rerank, series_anti_flood
from eventmind.domain.recommender.scoring import (
    EventFeatures,
    UserContext,
    cosine_similarity,
    freshness_score,
    rule_score,
)

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


# ── scoring ───────────────────────────────────────────────────────────────
def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert abs(cosine_similarity([1, 0], [0, 1])) < 1e-9
    assert cosine_similarity(None, [1, 0]) == 0.0
    assert cosine_similarity([1, 0], [1, 0, 0]) == 0.0  # разная длина


def test_freshness_decays_symmetrically() -> None:
    assert freshness_score(None, now=NOW) == 0.5
    assert freshness_score(NOW, now=NOW) == 1.0
    half = freshness_score(NOW + timedelta(days=30), now=NOW, half_life_days=30)
    assert abs(half - 0.5) < 1e-6
    past = freshness_score(NOW - timedelta(days=30), now=NOW, half_life_days=30)
    assert abs(past - 0.5) < 1e-6  # decay в обе стороны


def test_rule_score_topics_format_city() -> None:
    user = UserContext(
        topics={"backend"}, topic_weights={"backend": 3},
        preferred_format="offline", city="moscow",
    )
    event = EventFeatures(id=1, topics=["backend"], format="offline", city="moscow")
    # weight 3 + common(1)*2 + format(3) + city(2) = 10
    assert rule_score(user, event) == 10.0


# ── bayesian ────────────────────────────────────────────────────────────────
def test_feedback_delta() -> None:
    assert feedback_delta("like") == (3.0, 0.0)
    assert feedback_delta("dislike") == (0.0, 2.0)
    assert feedback_delta("save") == (1.0, 0.0)
    assert feedback_delta("like", -1) == (-3.0, 0.0)  # откат


def test_apply_decay_pulls_to_prior() -> None:
    old = NOW - timedelta(days=100)
    a, b = apply_decay(10.0, 5.0, old, now=NOW, gamma=0.9)
    assert 1.0 <= a < 10.0  # стянуто к prior, но не ниже
    assert 1.0 <= b < 5.0
    # свежая запись — почти без decay
    a2, b2 = apply_decay(10.0, 5.0, NOW, now=NOW, gamma=0.9)
    assert abs(a2 - 10.0) < 1e-6


def test_thompson_and_posterior() -> None:
    stats = {"backend": (20.0, 1.0), "frontend": (1.0, 20.0)}
    rng = random.Random(42)
    # backend с высоким alpha → высокий sample
    s = thompson_score(stats, ["backend"], rng=rng)
    assert 0.0 <= s <= 1.0
    assert thompson_score({}, [], rng=rng) == 0.0
    # posterior_mean детерминирован: backend ≈ 20/21
    assert posterior_mean(stats, ["backend"]) > 0.9
    assert posterior_mean(stats, ["frontend"]) < 0.1


# ── mmr + anti-flood ──────────────────────────────────────────────────────
def test_mmr_diversifies_second_pick() -> None:
    # 1 и 2 почти идентичны (высокий score), 3 — ортогонален
    items = [
        RankedItem(event_id=1, score=10.0, embedding=[1.0, 0.0]),
        RankedItem(event_id=2, score=9.9, embedding=[1.0, 0.01]),
        RankedItem(event_id=3, score=9.0, embedding=[0.0, 1.0]),
    ]
    out = mmr_rerank(items, lambda_=0.5)
    assert out[0].event_id == 1
    # второй выбор — ортогональный 3, а не почти-дубль 2
    assert out[1].event_id == 3


def test_series_anti_flood_keeps_closest_to_now() -> None:
    items = [
        RankedItem(event_id=1, score=5, series_slug="py", start_at=NOW + timedelta(days=40)),
        RankedItem(event_id=2, score=4, series_slug="py", start_at=NOW + timedelta(days=3)),
        RankedItem(event_id=3, score=3, series_slug=None, start_at=NOW + timedelta(days=1)),
    ]
    out = series_anti_flood(items, now=NOW)
    ids = [it.event_id for it in out]
    assert 2 in ids  # ближайший выпуск серии py остаётся
    assert 1 not in ids  # дальний выпуск отсеян
    assert 3 in ids  # без серии — не трогаем
