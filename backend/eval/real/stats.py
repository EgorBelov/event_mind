"""Метрики с градуированной релевантностью и статистика для сравнения систем.

Релевантность — оценка судьи 0..3. Неразмеченные события выдачи считаются
нерелевантными (стандарт пулинга TREC), доля размеченных в top-k
(`judged_at_k`) показывает, насколько этому можно доверять.

- nDCG@k: gain = 2^rel − 1, IDCG — по всем размеченным событиям персоны;
- P@k, Recall@k, AP@k — бинарно, «релевантно» = rel ≥ RELEVANT_THRESHOLD;
- бутстрап-интервал среднего, парный тест Уилкоксона (нормальная аппроксимация
  с поправкой на связки), каппа Коэна (в т.ч. квадратично взвешенная).
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence

from eval.real.data import RELEVANT_THRESHOLD


def _gain(rel: int) -> float:
    return float(2**rel - 1)


def ndcg_at_k(ranked: Sequence[int], rels: Mapping[int, int], k: int) -> float | None:
    """None — у персоны нет ни одного релевантного (rel>0) размеченного события."""
    ideal = sorted((r for r in rels.values() if r > 0), reverse=True)[:k]
    if not ideal:
        return None
    idcg = sum(_gain(r) / math.log2(i + 2) for i, r in enumerate(ideal))
    dcg = sum(_gain(rels.get(eid, 0)) / math.log2(i + 2) for i, eid in enumerate(ranked[:k]))
    return dcg / idcg


def precision_at_k(ranked: Sequence[int], rels: Mapping[int, int], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for eid in top if rels.get(eid, 0) >= RELEVANT_THRESHOLD) / len(top)


def recall_at_k(ranked: Sequence[int], rels: Mapping[int, int], k: int) -> float | None:
    relevant = {eid for eid, r in rels.items() if r >= RELEVANT_THRESHOLD}
    if not relevant:
        return None
    return len(relevant & set(ranked[:k])) / len(relevant)


def average_precision_at_k(
    ranked: Sequence[int], rels: Mapping[int, int], k: int
) -> float | None:
    relevant = {eid for eid, r in rels.items() if r >= RELEVANT_THRESHOLD}
    if not relevant:
        return None
    hits = 0
    total = 0.0
    for i, eid in enumerate(ranked[:k]):
        if eid in relevant:
            hits += 1
            total += hits / (i + 1)
    return total / min(len(relevant), k)


def judged_at_k(ranked: Sequence[int], rels: Mapping[int, int], k: int) -> float:
    top = ranked[:k]
    return sum(1 for eid in top if eid in rels) / len(top) if top else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(
    values: Sequence[float], *, n_resamples: int = 2000, alpha: float = 0.05, seed: int = 42
) -> tuple[float, float]:
    """Перцентильный бутстрап-интервал для среднего."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_resamples))
    low = means[int(alpha / 2 * n_resamples)]
    high = means[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    return (low, high)


def wilcoxon_signed_rank(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Парный тест Уилкоксона (двусторонний): (W, p-value).

    Нулевые разности отбрасываются; ранги со связками усредняются; p — по
    нормальной аппроксимации с поправкой на связки и непрерывность. Для n < 10
    аппроксимация грубая — так и указывать в отчёте.
    """
    diffs = [a - b for a, b in zip(x, y, strict=True) if abs(a - b) > 1e-12]
    n = len(diffs)
    if n == 0:
        return (0.0, 1.0)
    order = sorted(range(n), key=lambda i: abs(diffs[i]))
    ranks = [0.0] * n
    tie_term = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and math.isclose(abs(diffs[order[j + 1]]), abs(diffs[order[i]])):
            j += 1
        avg_rank = (i + j) / 2 + 1
        for idx in order[i : j + 1]:
            ranks[idx] = avg_rank
        t = j - i + 1
        tie_term += t**3 - t
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, diffs, strict=True) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, diffs, strict=True) if d < 0)
    w = min(w_plus, w_minus)
    mu = n * (n + 1) / 4
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - tie_term / 48)
    if sigma == 0:
        return (w, 1.0)
    z = (abs(w - mu) - 0.5) / sigma
    p = math.erfc(max(z, 0.0) / math.sqrt(2))
    return (w, min(1.0, p))


def cohen_kappa(
    a: Sequence[int], b: Sequence[int], *, categories: Sequence[int], quadratic: bool = False
) -> float:
    """Каппа Коэна для двух разметчиков; quadratic — квадратично взвешенная."""
    if len(a) != len(b) or not a:
        raise ValueError("нужны две непустые разметки одинаковой длины")
    cats = list(categories)
    index = {c: i for i, c in enumerate(cats)}
    m = len(cats)
    observed = [[0.0] * m for _ in range(m)]
    for x, y in zip(a, b, strict=True):
        observed[index[x]][index[y]] += 1
    n = float(len(a))
    row = [sum(observed[i]) / n for i in range(m)]
    col = [sum(observed[i][j] for i in range(m)) / n for j in range(m)]

    def weight(i: int, j: int) -> float:
        if quadratic:
            return ((i - j) / (m - 1)) ** 2 if m > 1 else 0.0
        return 0.0 if i == j else 1.0

    po = sum(weight(i, j) * observed[i][j] / n for i in range(m) for j in range(m))
    pe = sum(weight(i, j) * row[i] * col[j] for i in range(m) for j in range(m))
    if pe == 0:
        return 1.0
    return 1.0 - po / pe
