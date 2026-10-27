"""Unit: калибровка весов (P1 №10) — подбор по nDCG и логрегрессией на
синтетических пулах, кросс-валидация, переопределение весов в приложении."""
from __future__ import annotations

import pytest
from eval.real.calibrate import (
    COMPONENTS,
    Pool,
    coordinate_ascent,
    cross_validate,
    default_weights,
    logistic_regression,
    objective,
    rank_pool,
)

from eventmind.config import ConfigError, Settings, validate_config
from eventmind.domain.recommender.weights import ScoringWeights


def _pool(pid: str) -> Pool:
    """Релевантно то, что близко по смыслу (cosine), а quality «врёт»:
    у нерелевантных она выше. Веса по умолчанию тянут quality наверх."""
    events = list(range(1, 11))
    components = [
        {"cosine": 0.5 if e <= 3 else 0.3, "quality": 2.0 if e <= 3 else 9.0} for e in events
    ]
    return Pool(persona_id=pid, event_ids=events, components=components,
                rels={1: 3, 2: 3, 3: 2, 4: 0, 5: 0})


POOLS = [_pool(f"p{i}") for i in range(6)]


def test_rank_pool_is_linear_and_stable() -> None:
    ranked = rank_pool(POOLS[0], {"cosine": 1.0, "quality": 0.0}, k=3)
    assert ranked == [1, 2, 3]
    assert set(COMPONENTS) >= {"cosine", "quality", "skill_gap"}


def test_coordinate_ascent_beats_default_weights() -> None:
    before = objective(POOLS, default_weights())
    tuned = coordinate_ascent(POOLS)
    assert objective(POOLS, tuned) > before
    assert objective(POOLS, tuned) == pytest.approx(1.0)
    assert tuned["quality"] < default_weights()["quality"] or tuned["cosine"] > 10


def test_logistic_regression_prefers_informative_component() -> None:
    weights = logistic_regression(POOLS)
    assert weights["cosine"] > 0 and weights["quality"] == 0.0  # отрицательный → 0
    assert sum(weights.values()) == pytest.approx(sum(default_weights().values()))


def test_cross_validation_reports_held_out_scores() -> None:
    report = cross_validate(POOLS, method="coord", folds=3)
    assert len(report.folds) == 3 and report.n_personas == 6
    assert report.calibrated_mean > report.default_mean


def test_scoring_weights_overrides_and_validation() -> None:
    w = ScoringWeights.from_json('{"cosine": 12, "quality": 0}')
    assert w.cosine == 12.0 and w.quality == 0.0 and w.rule == ScoringWeights().rule
    assert ScoringWeights.from_json("") == ScoringWeights()
    for bad in ('{"unknown": 1}', '{"cosine": -1}', '{"cosine": true}', "[1]", "{bad"):
        with pytest.raises(ValueError):
            ScoringWeights.from_json(bad)
    settings = Settings(database_url="postgresql://x", redis_url="redis://x",
                        scoring_weights='{"cosine": "много"}')
    with pytest.raises(ConfigError, match="SCORING_WEIGHTS"):
        validate_config(settings, "api")
