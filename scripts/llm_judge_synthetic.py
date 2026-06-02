"""LLM-as-judge на синтетическом датасете.

Адаптация scripts/llm_judge.py для прогона на синтетическом датасете,
который строится в scripts/eval_offline_synthetic.py. Каждый пользователь
получает top-K по трём вариантам ранжирования (rule / hybrid / bayesian),
после чего одна и та же языковая модель в роли независимого эксперта
оценивает каждую карточку по двум шкалам 1–5:
  - relevance — соответствие интересам/целям пользователя;
  - diversity_contribution — вклад в разнообразие подборки.

Запуск:
    python -m scripts.llm_judge_synthetic --max-users 6 --k 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

from sqlalchemy.orm import Session

from app.db.models import Event, Topic, User, UserTopic
from app.recommender.bayesian import load_user_stats, posterior_mean
from app.recommender.hybrid import hybrid_score
from app.recommender.scoring import _get_event_topic_codes, score_event_for_user
from scripts.eval_offline_synthetic import build_synthetic_db

_JUDGE_SYSTEM = """\
Ты — независимый эксперт по IT-конференциям и митапам. Тебе дают профиль
пользователя и список рекомендованных событий. Оцени КАЖДОЕ событие по двум
шкалам (1–5):

- relevance: насколько событие соответствует интересам/целям пользователя.
- diversity_contribution: добавляет ли событие в подборку новизны/разнообразия.

Верни СТРОГО JSON-массив объектов длиной N (для каждого события один объект):
[
  {"event_id": 1, "relevance": 4, "diversity_contribution": 3},
  ...
]
Никакого текста вне массива.
"""


def _judge_via_llm(profile: dict, cards: list[dict]) -> list[dict]:
    # Не используем ChatPromptTemplate: фигурные скобки {"event_id": ...}
    # в системном промпте конфликтуют с placeholder-синтаксисом template'а.
    # Прямые SystemMessage/HumanMessage избегают этой проблемы.
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agents.recommendation.llm import llm
    user_text = (
        f"Профиль пользователя:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"Событий: {len(cards)}\n"
        f"Список:\n{json.dumps(cards, ensure_ascii=False, indent=2)}\n\n"
        f"Верни JSON-массив длиной {len(cards)}, по одному объекту на каждое событие."
    )
    response = llm.invoke([
        SystemMessage(content=_JUDGE_SYSTEM),
        HumanMessage(content=user_text),
    ])
    text = (response.content or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    # Иногда LLM добавляет ```json…``` обёртку — снимем заодно
    if text.startswith("[") and text.endswith("]"):
        pass
    else:
        # Попробуем выкусить JSON-массив из произвольного текста
        import re
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _top_k(db: Session, user: User, events: list[Event], k: int, variant: str) -> list[Event]:
    """Top-k событий для пользователя по выбранному варианту скоринга."""
    scored: list[tuple[Event, float]] = []
    bay = load_user_stats(db, user.id) or {} if variant == "bayesian" else {}
    for e in events:
        rs = float(score_event_for_user(user, e))
        if variant == "rule":
            s = rs
        else:
            try:
                hs = float(hybrid_score(user, e))
            except Exception:
                hs = rs
            if variant == "hybrid":
                s = hs
            else:  # bayesian
                pm = posterior_mean(bay, _get_event_topic_codes(e)) if bay else 0.5
                s = hs + pm * 5.0
        scored.append((e, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [e for e, _ in scored[:k]]


def _profile(db: Session, user: User) -> dict:
    topics = [
        t.code for t in db.query(Topic)
        .join(UserTopic, UserTopic.topic_id == Topic.id)
        .filter(UserTopic.user_id == user.id).all()
    ]
    return {
        "topics": topics,
        "preferred_format": user.preferred_format,
        "city": user.city,
    }


def _card(event: Event) -> dict:
    return {
        "event_id": event.id,
        "title": event.title,
        "topics": list(_get_event_topic_codes(event)),
        "format": event.format,
        "city": event.city,
    }


def _aggregate(judgements: list[dict]) -> tuple[float, float] | None:
    rels = [
        float(j["relevance"])
        for j in judgements
        if isinstance(j, dict) and isinstance(j.get("relevance"), int | float)
    ]
    divs = [
        float(j["diversity_contribution"])
        for j in judgements
        if isinstance(j, dict) and isinstance(j.get("diversity_contribution"), int | float)
    ]
    if not rels:
        return None
    return statistics.fmean(rels), statistics.fmean(divs) if divs else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--max-users", type=int, default=6)
    parser.add_argument(
        "--variants", nargs="+", default=["rule", "hybrid", "bayesian"],
    )
    args = parser.parse_args()

    print(f"Python: {sys.version.split()[0]}", flush=True)
    db = build_synthetic_db()
    try:
        users = db.query(User).limit(args.max_users).all()
        events = db.query(Event).all()
        print(f"\n=== Synthetic LLM-judge (k={args.k}, users={len(users)}) ===\n", flush=True)

        results: dict[str, dict] = {}
        for variant in args.variants:
            print(f"--- variant: {variant} ---", flush=True)
            rels_per_user: list[float] = []
            divs_per_user: list[float] = []
            for u in users:
                topk = _top_k(db, u, events, args.k, variant)
                if not topk:
                    continue
                cards = [_card(e) for e in topk]
                t0 = time.monotonic()
                try:
                    judgements = _judge_via_llm(_profile(db, u), cards)
                except Exception as e:
                    print(f"  user {u.id}: LLM-вызов упал ({e})", flush=True)
                    continue
                dt = time.monotonic() - t0
                agg = _aggregate(judgements)
                if agg is None:
                    print(f"  user {u.id}: пустые/невалидные оценки", flush=True)
                    continue
                rels_per_user.append(agg[0])
                divs_per_user.append(agg[1])
                print(
                    f"  user {u.id}: relevance={agg[0]:.2f}  "
                    f"diversity={agg[1]:.2f}  ({dt:.1f}s)",
                    flush=True,
                )
            if rels_per_user:
                rel_avg = statistics.fmean(rels_per_user)
                div_avg = statistics.fmean(divs_per_user)
                print(
                    f"  AVG  relevance={rel_avg:.3f}  diversity={div_avg:.3f}  "
                    f"users={len(rels_per_user)}\n",
                    flush=True,
                )
                results[variant] = {
                    "relevance_mean": round(rel_avg, 3),
                    "diversity_mean": round(div_avg, 3),
                    "users": len(rels_per_user),
                }
            else:
                print("  (нет валидных оценок)\n", flush=True)

        # Сводка
        print("=== Итоговая таблица ===", flush=True)
        print(f"{'variant':12}  {'relevance':>10}  {'diversity':>10}", flush=True)
        for v in args.variants:
            r = results.get(v, {})
            rel = f"{r.get('relevance_mean', '—'):>10}"
            div = f"{r.get('diversity_mean', '—'):>10}"
            print(f"{v:12}  {rel}  {div}", flush=True)

        with open("/tmp/llm_judge_results.json", "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("[saved] /tmp/llm_judge_results.json", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
