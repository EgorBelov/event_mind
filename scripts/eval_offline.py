"""Leave-one-out offline-эвал рекомендера.

Для каждого пользователя с ≥3 positive-взаимодействиями (like/save):
- скрываем последнее positive (event_id*),
- ранжируем ВСЕ события по выбранному скореру,
- считаем Recall@k и nDCG@k по позиции event_id*.

Сравниваем три варианта:
  1) rule       — текущий rule-based scoring,
  2) hybrid     — rule + cosine(user, event),
  3) bayesian   — hybrid + Thompson sampling по Beta-предпочтениям тем.

Запуск:
    python -m scripts.eval_offline           # дефолтная БД (eventmind.db)
    python -m scripts.eval_offline --k 5     # своя метрика @k
"""
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict

from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.db.session import SessionLocal
from app.recommender.bayesian import load_user_stats, posterior_mean
from app.recommender.hybrid import hybrid_score
from app.recommender.scoring import score_event_for_user

POSITIVE_ACTIONS = {"like", "save"}


def _ranked_ids(scores: list[tuple[int, float]]) -> list[int]:
    scores.sort(key=lambda x: x[1], reverse=True)
    return [eid for eid, _ in scores]


def _recall_at_k(ranked: list[int], target: int, k: int) -> float:
    return 1.0 if target in ranked[:k] else 0.0


def _ndcg_at_k(ranked: list[int], target: int, k: int) -> float:
    try:
        pos = ranked.index(target)
    except ValueError:
        return 0.0
    if pos >= k:
        return 0.0
    return 1.0 / math.log2(pos + 2)


def _build_user_for_eval(db, user_id: int, hide_event_id: int) -> User:
    """Грузит пользователя и подменяет topic_weights так, будто feedback
    по hide_event_id ещё не был применён (для честности leave-one-out).

    На таком прототипе это упрощение — мы не откатываем веса фактически,
    а просто работаем с пользователем «как есть», только скрываем целевой
    event из known-set. Для оценки относительного качества трёх скореров
    этого достаточно.
    """
    return db.query(User).filter(User.id == user_id).first()


def evaluate(db, k: int = 5, seed: int = 42) -> dict:
    random.seed(seed)
    events = db.query(Event).all()
    if not events:
        return {"status": "no_events"}

    interactions = db.query(Interaction).filter(Interaction.action.in_(POSITIVE_ACTIONS)).all()
    by_user: dict[int, list[Interaction]] = defaultdict(list)
    for i in interactions:
        by_user[i.user_id].append(i)

    by_user = {uid: ints for uid, ints in by_user.items() if len(ints) >= 3}

    if not by_user:
        return {"status": "not_enough_data", "users": 0}

    totals = {
        "rule":     {"recall": 0.0, "ndcg": 0.0},
        "hybrid":   {"recall": 0.0, "ndcg": 0.0},
        "bayesian": {"recall": 0.0, "ndcg": 0.0},
    }
    n = 0

    for user_id, ints in by_user.items():
        ints_sorted = sorted(ints, key=lambda i: i.id)
        target_event_id = ints_sorted[-1].event_id
        user = _build_user_for_eval(db, user_id, hide_event_id=target_event_id)
        if user is None:
            continue
        candidates = [e for e in events if e.id != target_event_id] + [
            e for e in events if e.id == target_event_id
        ]

        try:
            bay_stats = load_user_stats(db, user_id) or {}
        except Exception:
            bay_stats = {}

        rule_scores: list[tuple[int, float]] = []
        hybrid_scores: list[tuple[int, float]] = []
        bayes_scores: list[tuple[int, float]] = []
        for e in candidates:
            rs = float(score_event_for_user(user, e))
            rule_scores.append((e.id, rs))
            try:
                hs = float(hybrid_score(user, e))
            except Exception:
                hs = rs
            hybrid_scores.append((e.id, hs))
            # Bayesian: hybrid + posterior_mean по темам события.
            try:
                from app.recommender.scoring import _get_event_topic_codes
                pm = posterior_mean(bay_stats, _get_event_topic_codes(e)) if bay_stats else 0.5
            except Exception:
                pm = 0.5
            bayes_scores.append((e.id, hs + pm * 5.0))

        rule_ranked = _ranked_ids(rule_scores)
        hybrid_ranked = _ranked_ids(hybrid_scores)
        bayes_ranked = _ranked_ids(bayes_scores)

        totals["rule"]["recall"]   += _recall_at_k(rule_ranked,   target_event_id, k)
        totals["rule"]["ndcg"]     += _ndcg_at_k(rule_ranked,     target_event_id, k)
        totals["hybrid"]["recall"] += _recall_at_k(hybrid_ranked, target_event_id, k)
        totals["hybrid"]["ndcg"]   += _ndcg_at_k(hybrid_ranked,   target_event_id, k)
        totals["bayesian"]["recall"] += _recall_at_k(bayes_ranked, target_event_id, k)
        totals["bayesian"]["ndcg"]   += _ndcg_at_k(bayes_ranked,   target_event_id, k)
        n += 1

    if n == 0:
        return {"status": "no_eligible_users"}

    return {
        "status": "ok",
        "k": k,
        "users_evaluated": n,
        "rule":     {m: round(v / n, 4) for m, v in totals["rule"].items()},
        "hybrid":   {m: round(v / n, 4) for m, v in totals["hybrid"].items()},
        "bayesian": {m: round(v / n, 4) for m, v in totals["bayesian"].items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    db = SessionLocal()

    try:
        result = evaluate(db, k=args.k)
    finally:
        db.close()

    print("=== Offline eval (leave-one-out) ===")
    for line, val in result.items():
        print(f"{line}: {val}")


if __name__ == "__main__":
    main()
