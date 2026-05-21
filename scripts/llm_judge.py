"""LLM-as-judge для оффлайн-эвала рекомендера.

Сценарий:
1. Для каждого пользователя из БД берём текущие top-K рекомендаций (rule / hybrid / bandit-on).
2. LLM получает {профиль, цель/интересы, список карточек} и оценивает каждое:
       relevance: 1–5 (насколько подходит юзеру)
       diversity_contribution: 1–5 (привносит ли разнообразие)
3. Усредняем по пользователям → таблица сравнения скореров.

Запуск:
    python -m scripts.llm_judge --k 5 --variants rule hybrid bandit_on
"""
from __future__ import annotations

import argparse
import json
import statistics

from app.core.config import settings
from app.db.session import SessionLocal


_JUDGE_SYSTEM = """\
Ты — независимый эксперт по IT-конференциям и митапам. Тебе дают профиль
пользователя и список рекомендованных событий. Оцени КАЖДОЕ событие по двум
шкалам (1–5):

- relevance: насколько событие соответствует интересам/целям пользователя.
- diversity_contribution: добавляет ли событие в подборку новизны/разнообразия.

Верни СТРОГО JSON-массив объектов:
[
  {"event_id": 1, "relevance": 4, "diversity_contribution": 3, "comment": "коротко"},
  ...
]
"""


def _judge_via_llm(profile: dict, cards: list[dict]) -> list[dict]:
    from langchain_core.prompts import ChatPromptTemplate
    from app.agents.recommendation.llm import llm
    prompt = ChatPromptTemplate.from_messages([
        ("system", _JUDGE_SYSTEM),
        ("user", "Профиль пользователя:\n{profile}\n\nСобытия:\n{cards}\n\n"
                 "Верни JSON-массив длиной {n} (для каждого события один объект)."),
    ])
    msg = prompt.format_messages(
        profile=json.dumps(profile, ensure_ascii=False),
        cards=json.dumps(cards, ensure_ascii=False),
        n=len(cards),
    )
    response = llm.invoke(msg)
    text = (response.content or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def evaluate_user_variant(db, user, k: int, variant: str) -> list[dict]:
    """Получить top-k для пользователя + LLM-оценку."""
    from app.api.services.recommendation_service import get_recommendations_for_user
    from app.core.config import settings as _settings

    # Гасим bandit для variant=hybrid (имитируем «как было до bandit'а»).
    old_bandit, old_gnn = _settings.bandit_enabled, _settings.gnn_enabled
    if variant == "rule":
        _settings.bandit_enabled = False
        _settings.gnn_enabled = False
        # Заглушаем cosine/bayes тоже, чтобы остался чистый rule:
        old_cosine, old_bayes = _settings.score_cosine_weight, _settings.score_bayes_weight
        _settings.score_cosine_weight = 0.0
        _settings.score_bayes_weight = 0.0
    elif variant == "hybrid":
        _settings.bandit_enabled = False
        _settings.gnn_enabled = False
    # else: bandit_on — оставляем как есть

    try:
        recs = get_recommendations_for_user(db, user.telegram_id)[:k]
    except Exception:
        recs = []
    finally:
        _settings.bandit_enabled = old_bandit
        _settings.gnn_enabled = old_gnn
        if variant == "rule":
            _settings.score_cosine_weight = old_cosine
            _settings.score_bayes_weight = old_bayes

    if not recs:
        return []

    profile = {
        "topics": [t.topic.code for t in (user.user_topics or []) if t.topic],
        "preferred_format": user.preferred_format,
        "city": user.city,
    }
    cards = [
        {"event_id": r["event_id"], "title": r["title"], "topics": r["topics"]}
        for r in recs
    ]
    judgements = _judge_via_llm(profile, cards)
    return judgements


def aggregate(judgements: list[dict]) -> dict:
    rels = [int(j.get("relevance", 0)) for j in judgements if isinstance(j.get("relevance"), (int, float))]
    divs = [int(j.get("diversity_contribution", 0)) for j in judgements if isinstance(j.get("diversity_contribution"), (int, float))]
    return {
        "n": len(judgements),
        "relevance_mean": round(statistics.fmean(rels), 3) if rels else 0.0,
        "diversity_mean": round(statistics.fmean(divs), 3) if divs else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--variants", nargs="+", default=["rule", "hybrid", "bandit_on"])
    parser.add_argument("--max-users", type=int, default=10)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        from app.db.models.user import User
        users = db.query(User).limit(args.max_users).all()
        if not users:
            print("Нет пользователей для эвала.")
            return

        print(f"=== LLM-judge (k={args.k}, users={len(users)}) ===")
        for variant in args.variants:
            all_rels, all_divs = [], []
            for u in users:
                j = evaluate_user_variant(db, u, args.k, variant)
                stats = aggregate(j)
                if stats["n"]:
                    all_rels.append(stats["relevance_mean"])
                    all_divs.append(stats["diversity_mean"])
            print(f"\n--- variant: {variant} ---")
            if all_rels:
                print(f"avg relevance: {statistics.fmean(all_rels):.3f}")
                print(f"avg diversity: {statistics.fmean(all_divs):.3f}")
                print(f"users with judgements: {len(all_rels)}")
            else:
                print("(нет данных)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
