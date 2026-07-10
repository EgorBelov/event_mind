"""Unit: offline-eval harness — детерминизм (seed=42), границы метрик, абляции."""
from __future__ import annotations

from eval.harness import KS, run_evaluation
from eval.metrics import average_precision, ndcg_at_k, recall_at_k
from eval.synthetic import build_dataset


def test_dataset_is_deterministic() -> None:
    a = build_dataset(42)
    b = build_dataset(42)
    assert len(a.users) == len(b.users)
    assert [u.target_event_id for u in a.users] == [u.target_event_id for u in b.users]


def test_evaluation_is_reproducible() -> None:
    r1 = run_evaluation(42)
    r2 = run_evaluation(42)
    m1 = {v.variant: (v.recall, v.ndcg, v.map) for v in r1.results}
    m2 = {v.variant: (v.recall, v.ndcg, v.map) for v in r2.results}
    assert m1 == m2


def test_metrics_within_bounds() -> None:
    report = run_evaluation(42)
    for v in report.results:
        for k in KS:
            assert 0.0 <= v.recall[k] <= 1.0
            assert 0.0 <= v.ndcg[k] <= 1.0
        assert 0.0 <= v.map <= 1.0
        assert 0.0 <= v.coverage_at_10 <= 1.0
        assert 0.0 <= v.diversity_at_10 <= 1.0


def test_recall_is_monotonic_in_k() -> None:
    report = run_evaluation(42)
    for v in report.results:
        vals = [v.recall[k] for k in KS]
        assert vals == sorted(vals)  # Recall@k не убывает с ростом k


def test_full_model_competitive_and_mmr_adds_diversity() -> None:
    by_name = {v.variant: v for v in run_evaluation(42).results}
    full = by_name["full"]
    no_mmr = by_name["full_no_mmr"]
    # комбинированная модель — на уровне лучших по Recall@10 и лидер по top-1
    assert full.recall[10] >= by_name["bayesian_only"].recall[10]
    assert full.recall[1] >= by_name["content_only"].recall[1]
    # MMR повышает разнообразие головы (ценой части точности)
    assert full.diversity_at_10 >= no_mmr.diversity_at_10


def test_metric_helpers_edge_cases() -> None:
    assert recall_at_k([3, 1, 2], target_id=1, k=2) == 1.0
    assert recall_at_k([3, 1, 2], target_id=9, k=2) == 0.0
    assert ndcg_at_k([5, 7], target_id=5, k=2) == 1.0  # rank 1 → 1/log2(2)=1
    assert average_precision([9, 8, 4], target_id=4) == 1.0 / 3
