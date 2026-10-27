"""Веса гибридного скоринга и параметры rerank/decay.

Значения по умолчанию — эмпирические из v1. Откалиброванные веса (P1 №10,
`python -m eval.real.calibrate`) подставляются через настройку
`SCORING_WEIGHTS` (JSON) — `ScoringWeights.with_overrides`.
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
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
    skill_gap: float = 3.0  # событие закрывает навык для цели: 0..1 → до +3 (P1 №18)
    bandit: float = 2.0     # задел (LinUCB — расширение)
    gnn: float = 3.0        # задел (LightGCN — выкл. по умолчанию)

    # Параметры.
    freshness_half_life_days: float = 30.0
    bayes_decay_per_day: float = 0.995
    mmr_lambda: float = 0.7
    dedup_threshold: float = 0.92

    def with_overrides(self, overrides: Mapping[str, object]) -> ScoringWeights:
        """Копия с заменёнными полями; неизвестное поле или не число ≥ 0 — ValueError."""
        known = {f.name for f in dataclasses.fields(self)}
        clean: dict[str, float] = {}
        for key, value in overrides.items():
            if key not in known:
                raise ValueError(f"Неизвестный вес скоринга: {key}")
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
                raise ValueError(f"Вес {key} должен быть числом ≥ 0")
            clean[key] = float(value)
        return dataclasses.replace(self, **clean)

    @classmethod
    def from_json(cls, raw: str) -> ScoringWeights:
        """Из настройки SCORING_WEIGHTS: пусто — значения по умолчанию."""
        if not raw.strip():
            return cls()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("SCORING_WEIGHTS должен быть JSON-объектом")
        return cls().with_overrides(data)
