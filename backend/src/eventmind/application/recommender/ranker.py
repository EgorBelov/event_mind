"""HybridRanker — взвешенная сумма компонентов + MMR + series anti-flood.

Каждый компонент в try/except (сбой одного не рушит выдачу — деградация).
Веса и математика — из `domain/recommender`. Скореры-заделы (skill_gap/bandit/
gnn) включаются флагами позже; сейчас активны rule/cosine/bayesian/quality/
hype/freshness.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from eventmind.domain.recommender.bayesian import thompson_score
from eventmind.domain.recommender.mmr import RankedItem, mmr_rerank, series_anti_flood
from eventmind.domain.recommender.scoring import (
    EventFeatures,
    UserContext,
    cosine_similarity,
    freshness_score,
    rule_score,
)
from eventmind.domain.recommender.weights import ScoringWeights

_logger = structlog.get_logger("eventmind.recommender")

BayesianStats = dict[str, tuple[float, float]]


@dataclass(slots=True)
class ScoredEvent:
    event_id: int
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)


class HybridRanker:
    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self._w = weights or ScoringWeights()

    def _breakdown(
        self,
        user: UserContext,
        event: EventFeatures,
        stats: BayesianStats,
        *,
        now: datetime,
        rng: random.Random,
    ) -> dict[str, float]:
        w = self._w
        out: dict[str, float] = {}

        def safe(name: str, fn: Callable[[], float]) -> None:
            try:
                out[name] = float(fn())
            except Exception as exc:
                _logger.warning("scorer_failed", scorer=name, event=event.id, error=str(exc))
                out[name] = 0.0

        safe("rule", lambda: rule_score(user, event) * w.rule)
        safe("cosine", lambda: cosine_similarity(user.embedding, event.embedding) * w.cosine)
        safe("bayesian", lambda: thompson_score(stats, event.topics, rng=rng) * w.bayesian)
        safe("quality", lambda: (event.quality_score or 0) * w.quality)
        safe("hype", lambda: (event.hype_score or 0) * w.hype)
        safe(
            "freshness",
            lambda: freshness_score(
                event.start_at, now=now, half_life_days=w.freshness_half_life_days
            )
            * w.freshness,
        )
        return out

    def rank(
        self,
        user: UserContext,
        events: list[EventFeatures],
        stats: BayesianStats,
        *,
        now: datetime,
        limit: int = 20,
        rng: random.Random | None = None,
    ) -> list[ScoredEvent]:
        rng = rng or random.Random()
        scored: list[ScoredEvent] = []
        by_features: dict[int, EventFeatures] = {}
        for ev in events:
            breakdown = self._breakdown(user, ev, stats, now=now, rng=rng)
            scored.append(
                ScoredEvent(event_id=ev.id, score=sum(breakdown.values()), breakdown=breakdown)
            )
            by_features[ev.id] = ev

        scored.sort(key=lambda s: s.score, reverse=True)

        # MMR-диверсификация головы + анти-флуд серий.
        ranked_items = [
            RankedItem(
                event_id=s.event_id,
                score=s.score,
                embedding=by_features[s.event_id].embedding,
                series_slug=by_features[s.event_id].series_slug,
                start_at=by_features[s.event_id].start_at,
            )
            for s in scored
        ]
        ranked_items = mmr_rerank(ranked_items, lambda_=self._w.mmr_lambda)
        ranked_items = series_anti_flood(ranked_items, now=now)

        score_by_id = {s.event_id: s for s in scored}
        return [score_by_id[it.event_id] for it in ranked_items[:limit]]
