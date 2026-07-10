"""Leave-one-out прогон HybridRanker по абляциям + агрегация метрик.

Каждая абляция — вариант `ScoringWeights` (rule-only / content-only /
bayesian-only / full / full-no-MMR). rng сидируется детерминированно на
(вариант, пользователь), поэтому Thompson-sampling воспроизводим.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from eval.metrics import (
    average_precision,
    catalog_coverage,
    intra_list_diversity,
    ndcg_at_k,
    recall_at_k,
)
from eval.synthetic import Dataset, build_dataset
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.recommender.weights import ScoringWeights

KS = (1, 3, 5, 10)
NOW = datetime(2026, 7, 10, tzinfo=UTC)

_ZERO = {"cosine": 0.0, "bayesian": 0.0, "rule": 0.0, "quality": 0.0, "hype": 0.0, "freshness": 0.0}


def default_variants() -> dict[str, ScoringWeights]:
    """Именованные абляции весов (для сравнения вклада компонентов)."""
    base = ScoringWeights()
    return {
        "rule_only": ScoringWeights(**{**_ZERO, "rule": base.rule}),
        "content_only": ScoringWeights(**{**_ZERO, "cosine": base.cosine}),
        "bayesian_only": ScoringWeights(**{**_ZERO, "bayesian": base.bayesian}),
        "full": base,
        "full_no_mmr": dataclasses.replace(base, mmr_lambda=1.0),
    }


@dataclass(slots=True)
class VariantResult:
    variant: str
    recall: dict[int, float] = field(default_factory=dict)
    ndcg: dict[int, float] = field(default_factory=dict)
    map: float = 0.0
    coverage_at_10: float = 0.0
    diversity_at_10: float = 0.0


@dataclass(slots=True)
class EvalReport:
    seed: int
    n_users: int
    n_events: int
    results: list[VariantResult]


def _rank_ids(
    ranker: HybridRanker, dataset: Dataset, user_index: int, seed: int
) -> list[int]:
    user = dataset.users[user_index]
    by_id = dataset.events_by_id
    candidates = [by_id[cid] for cid in user.candidate_ids]
    rng = random.Random(seed + user_index)
    ranked = ranker.rank(
        user.context, candidates, user.stats, now=NOW, limit=len(candidates), rng=rng
    )
    return [s.event_id for s in ranked]


def evaluate_variant(
    dataset: Dataset, name: str, weights: ScoringWeights, *, seed: int
) -> VariantResult:
    ranker = HybridRanker(weights)
    res = VariantResult(variant=name)
    recall_acc = {k: 0.0 for k in KS}
    ndcg_acc = {k: 0.0 for k in KS}
    ap_acc = 0.0
    recommended: set[int] = set()
    diversity_acc = 0.0
    n = len(dataset.users)

    for ui in range(n):
        ranked_ids = _rank_ids(ranker, dataset, ui, seed)
        target = dataset.users[ui].target_event_id
        for k in KS:
            recall_acc[k] += recall_at_k(ranked_ids, target, k)
            ndcg_acc[k] += ndcg_at_k(ranked_ids, target, k)
        ap_acc += average_precision(ranked_ids, target)
        recommended.update(ranked_ids[:10])
        diversity_acc += intra_list_diversity(ranked_ids[:10], dataset.event_embeddings)

    res.recall = {k: recall_acc[k] / n for k in KS}
    res.ndcg = {k: ndcg_acc[k] / n for k in KS}
    res.map = ap_acc / n
    res.coverage_at_10 = catalog_coverage(recommended, len(dataset.events))
    res.diversity_at_10 = diversity_acc / n
    return res


def run_evaluation(
    seed: int = 42, variants: dict[str, ScoringWeights] | None = None
) -> EvalReport:
    dataset = build_dataset(seed)
    variants = variants or default_variants()
    results = [
        evaluate_variant(dataset, name, weights, seed=seed)
        for name, weights in variants.items()
    ]
    return EvalReport(
        seed=seed,
        n_users=len(dataset.users),
        n_events=len(dataset.events),
        results=results,
    )
