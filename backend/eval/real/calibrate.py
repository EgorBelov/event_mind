"""Калибровка весов гибрида по разметке LLM-судьи (P1 №10).

Веса по умолчанию — эмпирические из v1. Здесь их подбирают так, чтобы выдача
HybridRanker лучше совпадала с оценками релевантности (nDCG@10), с
кросс-валидацией по персонам, чтобы не подогнать веса под разметку.

1. Для каждой персоны — пул кандидатов той же двухстадийной схемой, что в
   приложении (kNN по эмбеддингу профиля → top-N), и «сырые» компоненты
   скоринга каждого кандидата (`HybridRanker.explain` с единичными весами).
   Балл = Σ wᵢ·cᵢ — линейная модель, поэтому разный масштаб компонент
   (rule ~0..15, cosine 0..1) поглощают веса, отдельная нормализация не нужна.
2. Методы:
   - `coord` — покоординатный подъём по сетке множителей прямо по nDCG@10
     (метрика не дифференцируема — оптимизируем её саму);
   - `logreg` — логистическая регрессия «релевантно (≥2) / нет» по компонентам
     (pointwise, L2), коэффициенты → веса (отрицательные обнуляются).
3. k-fold по персонам: подбор на k−1 частях, nDCG на отложенной — сравнение с
   весами по умолчанию. Итоговые веса (на всех персонах) печатаются JSON для
   `SCORING_WEIGHTS`.

MMR и анти-флуд серий в калибровке не участвуют (это переранжирование ради
разнообразия, а не релевантности); Bayesian на холодном старте равен 0 — его
вес по этим данным не калибруется и остаётся прежним.

    python -m eval.real.calibrate --encoder minilm --method coord
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from eval.real.data import RELEVANT_THRESHOLD, ExtractedPersona, Persona
from eval.real.stats import mean, ndcg_at_k
from eval.real.systems import HybridSystem, event_features, user_context
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.domain.recommender.weights import ScoringWeights

K = 10
# Калибруемые компоненты (bayesian на холодном старте всегда 0 — не калибруется).
COMPONENTS: tuple[str, ...] = ("rule", "cosine", "skill_gap", "quality", "hype", "freshness")
GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

Weights = dict[str, float]


def default_weights() -> Weights:
    w = ScoringWeights()
    return {c: float(getattr(w, c)) for c in COMPONENTS}


def unit_weights() -> ScoringWeights:
    """Все веса компонент = 1: `explain` вернёт сырые значения компонент."""
    return dataclasses.replace(
        ScoringWeights(), **{c: 1.0 for c in (*COMPONENTS, "bayesian")}
    )


@dataclass(slots=True)
class Pool:
    persona_id: str
    event_ids: list[int]
    components: list[dict[str, float]]  # сырые компоненты кандидатов
    rels: dict[int, int]


def build_pools(
    system: HybridSystem,
    personas: Sequence[Persona],
    rels: Mapping[str, Mapping[int, int]],
) -> list[Pool]:
    """Пулы кандидатов с компонентами; персоны без релевантных событий пропускаются
    (nDCG для них не определён)."""
    ranker = HybridRanker(unit_weights())
    pools: list[Pool] = []
    for persona in personas:
        pr = dict(rels.get(persona.id, {}))
        if not any(r >= RELEVANT_THRESHOLD for r in pr.values()):
            continue
        query = system.persona_vectors.get(persona.id)
        extracted: ExtractedPersona | None = system.extracted.get(persona.id)
        ctx = user_context(persona, extracted, query)
        candidates = system._candidates(query)
        components = [
            ranker.explain(
                ctx, event_features(ev, system.event_vectors.get(ev.id)), {}, now=system.now
            )
            for ev in candidates
        ]
        pools.append(
            Pool(
                persona_id=persona.id,
                event_ids=[ev.id for ev in candidates],
                components=components,
                rels=pr,
            )
        )
    return pools


def rank_pool(pool: Pool, weights: Mapping[str, float], k: int = K) -> list[int]:
    scored = [
        (sum(weights.get(c, 0.0) * comp.get(c, 0.0) for c in COMPONENTS), eid)
        for eid, comp in zip(pool.event_ids, pool.components, strict=True)
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [eid for _, eid in scored[:k]]


def objective(pools: Sequence[Pool], weights: Mapping[str, float], k: int = K) -> float:
    return mean([ndcg_at_k(rank_pool(p, weights, k), p.rels, k) or 0.0 for p in pools])


def coordinate_ascent(
    pools: Sequence[Pool], start: Weights | None = None, *, passes: int = 3, k: int = K
) -> Weights:
    """Покоординатный подъём: по очереди для каждой компоненты пробуем
    base·m для m из сетки, оставляем лучшее; повторяем, пока есть улучшение."""
    weights = dict(start or default_weights())
    best = objective(pools, weights, k)
    for _ in range(passes):
        improved = False
        for comp in COMPONENTS:
            base = weights[comp] or default_weights()[comp] or 1.0
            for m in GRID:
                trial = {**weights, comp: base * m}
                score = objective(pools, trial, k)
                if score > best + 1e-9:
                    best, weights, improved = score, trial, True
        if not improved:
            break
    return weights


def logistic_regression(
    pools: Sequence[Pool], *, epochs: int = 300, lr: float = 0.1, l2: float = 0.01
) -> Weights:
    """Pointwise-логрегрессия «релевантно / нет» по стандартизованным
    компонентам; веса = коэффициенты / std (отрицательные → 0), масштаб —
    как у суммы весов по умолчанию (ранжирование от масштаба не зависит)."""
    rows = [
        (
            [comp.get(c, 0.0) for c in COMPONENTS],
            1.0 if p.rels[eid] >= RELEVANT_THRESHOLD else 0.0,
        )
        for p in pools
        for eid, comp in zip(p.event_ids, p.components, strict=True)
        if eid in p.rels  # только размеченные пары
    ]
    if not rows:
        return default_weights()
    n_feat = len(COMPONENTS)
    means = [mean([x[j] for x, _ in rows]) for j in range(n_feat)]
    stds = [
        math.sqrt(mean([(x[j] - means[j]) ** 2 for x, _ in rows])) or 1.0 for j in range(n_feat)
    ]
    data = [([(x[j] - means[j]) / stds[j] for j in range(n_feat)], y) for x, y in rows]
    coef = [0.0] * n_feat
    bias = 0.0
    for _ in range(epochs):
        grad = [0.0] * n_feat
        grad_b = 0.0
        for x, y in data:
            z = bias + sum(c * v for c, v in zip(coef, x, strict=True))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - y
            for j in range(n_feat):
                grad[j] += err * x[j]
            grad_b += err
        coef = [c - lr * (g / len(data) + l2 * c) for c, g in zip(coef, grad, strict=True)]
        bias -= lr * grad_b / len(data)
    raw = {c: max(0.0, coef[j] / stds[j]) for j, c in enumerate(COMPONENTS)}
    total, target = sum(raw.values()), sum(default_weights().values())
    return {c: (v / total * target if total else default_weights()[c]) for c, v in raw.items()}


@dataclass(slots=True)
class FoldResult:
    fold: int
    default: float
    calibrated: float
    weights: Weights


@dataclass(slots=True)
class CalibrationReport:
    method: str
    n_personas: int
    folds: list[FoldResult]
    default_mean: float
    calibrated_mean: float
    weights: Weights  # подобраны на всех персонах — для SCORING_WEIGHTS


def fit(pools: Sequence[Pool], method: str) -> Weights:
    if method == "logreg":
        return logistic_regression(pools)
    return coordinate_ascent(pools)


def cross_validate(
    pools: Sequence[Pool], *, method: str = "coord", folds: int = 3, seed: int = 42
) -> CalibrationReport:
    order = list(pools)
    random.Random(seed).shuffle(order)
    parts = [order[i::folds] for i in range(folds)] if len(order) >= folds else [order]
    results: list[FoldResult] = []
    for i, test in enumerate(parts):
        train = [p for j, part in enumerate(parts) if j != i for p in part] or test
        weights = fit(train, method)
        results.append(
            FoldResult(
                fold=i,
                default=objective(test, default_weights()),
                calibrated=objective(test, weights),
                weights=weights,
            )
        )
    return CalibrationReport(
        method=method,
        n_personas=len(pools),
        folds=results,
        default_mean=mean([r.default for r in results]),
        calibrated_mean=mean([r.calibrated for r in results]),
        weights=fit(pools, method),
    )


def format_report(report: CalibrationReport) -> str:
    lines = [
        f"=== Калибровка весов гибрида ({report.method}, персон={report.n_personas}, "
        f"nDCG@{K} на отложенных частях) ===",
        *(
            f"fold {r.fold}: по умолчанию {r.default:.3f} → откалиброванные {r.calibrated:.3f}"
            for r in report.folds
        ),
        f"среднее: {report.default_mean:.3f} → {report.calibrated_mean:.3f}",
        "",
        "SCORING_WEIGHTS=" + json.dumps({k: round(v, 3) for k, v in report.weights.items()}),
    ]
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> None:
    from eval.real.data import load_events, load_extracted, load_labels, load_personas
    from eval.real.encoders import ENCODERS, EmbeddingCache, sentence_transformer_encode_fn
    from eval.real.systems import event_text, persona_text

    spec = ENCODERS[args.encoder]
    encode = sentence_transformer_encode_fn(spec)
    cache = EmbeddingCache(spec)
    events = load_events()
    personas = load_personas()
    extracted = load_extracted()
    event_vectors = dict(
        zip(
            (ev.id for ev in events),
            await cache.passages([event_text(ev) for ev in events], encode),
            strict=True,
        )
    )
    persona_vectors = dict(
        zip(
            (p.id for p in personas),
            await cache.queries([persona_text(p, extracted.get(p.id)) for p in personas], encode),
            strict=True,
        )
    )
    rels: dict[str, dict[int, int]] = {}
    for (pid, eid), label in load_labels().items():
        rels.setdefault(pid, {})[eid] = label.relevance
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    system = HybridSystem(
        name=f"hybrid:{args.encoder}", events=events, extracted=extracted,
        persona_vectors=persona_vectors, event_vectors=event_vectors, now=now,
    )
    report = cross_validate(build_pools(system, personas, rels), method=args.method)
    print(format_report(report))


def main() -> None:
    parser = argparse.ArgumentParser(description="Калибровка весов гибрида (P1 №10)")
    parser.add_argument("--encoder", default="minilm")
    parser.add_argument("--method", choices=("coord", "logreg"), default="coord")
    parser.add_argument("--now", default="", help="«сегодня» для корпуса, ISO-8601")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
