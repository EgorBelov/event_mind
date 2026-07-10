"""Веса гибридного скоринга и параметры rerank/decay (значения из v1)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    # Веса компонентов (подобраны эмпирически в v1).
    rule: float = 0.5
    cosine: float = 10.0
    bayesian: float = 5.0
    quality: float = 0.5   # quality_score 1..10 → до +5
    hype: float = 0.3      # hype_score 1..10 → до +3
    freshness: float = 2.0  # freshness 0..1 → до +2
    skill_gap: float = 3.0  # задел (скорер включается флагом позже)
    bandit: float = 2.0     # задел (LinUCB — расширение)
    gnn: float = 3.0        # задел (LightGCN — выкл. по умолчанию)

    # Параметры.
    freshness_half_life_days: float = 30.0
    bayes_decay_per_day: float = 0.995
    mmr_lambda: float = 0.7
    dedup_threshold: float = 0.92
