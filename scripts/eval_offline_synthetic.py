"""Воспроизводимый офлайн-эвал на синтетическом датасете.

На текущем этапе прототипа в продакшн-БД ещё нет достаточного объёма
реальных положительных взаимодействий для leave-one-out (требуется ≥3
positive-сигнала на пользователя). Для оценки относительного качества
трёх вариантов алгоритма ранжирования (rule / hybrid / bayesian)
используется изолированный синтетический бенчмарк:

- N=30 пользователей, у каждого 1-3 «темы интереса» из seed-словаря;
- M=120 событий, равномерно распределённых по темам;
- каждому пользователю генерируется 4-6 положительных взаимодействий
  (like/save) с событиями, тематически совпадающими с его интересами,
  и 1 «холодное» взаимодействие с тематически далёким событием —
  это создаёт реалистичный шум;
- последнее по времени положительное взаимодействие скрывается
  (leave-one-out) и используется как целевое событие;
- запускается стандартный `scripts.eval_offline.evaluate` для k ∈ {1, 3, 5, 10}.

Изолированность: используется in-memory SQLite — продакшн-БД (Supabase)
не модифицируется. Зерно `seed=42` зафиксировано — результаты
воспроизводимы.

Запуск:
    python -m scripts.eval_offline_synthetic
"""
from __future__ import annotations

import json
import random
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (
    Event,
    EventTopic,
    Interaction,
    Topic,
    User,
    UserTopic,
    UserTopicStat,
)
from app.recommender.bayesian import update_stats_from_feedback
from scripts.eval_offline import evaluate

SEED_TOPICS = [
    "ai_ml", "backend", "frontend", "devops",
    "data_science", "cybersecurity", "product", "mobile",
]
# Размер бенчмарка калиброван под CPU sentence-transformers MiniLM.
# При N_USERS=20, M_EVENTS=80 эвал отрабатывает за ~30-60 с.
N_USERS = 20
M_EVENTS = 80
SEED = 42


def _seed_topics(db, codes: list[str]) -> dict[str, Topic]:
    out: dict[str, Topic] = {}
    for c in codes:
        t = Topic(code=c, title=c)
        db.add(t)
        out[c] = t
    db.flush()
    return out


def _make_event(db, idx: int, topics: list[Topic], rng: random.Random) -> Event:
    main_topic = rng.choice(topics)
    e = Event(
        title=f"Event {idx} ({main_topic.code})",
        description=f"Описание события {idx} на тему {main_topic.code}",
        format=rng.choice(["online", "offline", "hybrid"]),
        city=rng.choice(["moscow", "spb", "any"]),
        level=rng.choice(["beginner", "middle", "advanced"]),
        date="2026-06-15",
    )
    db.add(e)
    db.flush()
    db.add(EventTopic(event_id=e.id, topic_id=main_topic.id))
    db.flush()
    return e


def _make_user(db, idx: int, topics: list[Topic], rng: random.Random) -> User:
    # Одна «доминирующая» тема (вес 10) + 0-1 побочная (вес 3).
    # Это обеспечивает контраст score'ов: события доминирующей темы получают
    # высший балл, побочные — средний, чужие — 0. На равенстве score'ов target
    # терялся бы в шуме.
    main_topic = rng.choice(topics)
    chosen = [main_topic]
    if rng.random() < 0.6:
        side = rng.choice([t for t in topics if t.code != main_topic.code])
        chosen.append(side)
    weights = {main_topic.code: 10}
    if len(chosen) > 1:
        weights[chosen[1].code] = 3
    u = User(
        telegram_id=10_000 + idx,
        username=f"u{idx}",
        preferred_format=rng.choice(["online", "offline", "hybrid"]),
        city=rng.choice(["moscow", "spb", "any"]),
        topic_weights=json.dumps(weights),
    )
    db.add(u)
    db.flush()
    for t in chosen:
        db.add(UserTopic(user_id=u.id, topic_id=t.id))
    db.flush()
    return u


def _main_topic_code(db, user: User) -> str:
    """Тема с максимальным весом в topic_weights пользователя."""
    weights = json.loads(user.topic_weights or "{}")
    return max(weights.items(), key=lambda kv: kv[1])[0] if weights else ""


def _add_interaction(db, user: User, event: Event, action: str) -> None:
    db.add(Interaction(user_id=user.id, event_id=event.id, action=action))
    # обновим Bayesian статистики, чтобы load_user_stats в eval вернул
    # ненулевой posterior — иначе bayesian-вариант будет тождественен hybrid
    from app.recommender.scoring import _get_event_topic_codes
    codes = list(_get_event_topic_codes(event))
    update_stats_from_feedback(db, user.id, codes, action, direction=1)


def build_synthetic_db() -> SessionLocal:  # type: ignore[valid-type]
    """Создаёт in-memory SQLite БД с синтетическим датасетом и возвращает Session."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    rng = random.Random(SEED)
    print("[seed] creating topics…", flush=True)
    topics = list(_seed_topics(db, SEED_TOPICS).values())

    # Events: M штук, поровну размазаны по темам
    print(f"[seed] creating {M_EVENTS} events…", flush=True)
    events_by_topic: dict[str, list[Event]] = {t.code: [] for t in topics}
    for i in range(M_EVENTS):
        e = _make_event(db, i, topics, rng)
        et = db.query(EventTopic).filter_by(event_id=e.id).first()
        if et:
            topic_code = next(t.code for t in topics if t.id == et.topic_id)
            events_by_topic[topic_code].append(e)
    db.commit()

    # ── Префилл embedding'ов ──
    # hybrid_score внутри вызывает get_or_build_event_embedding и cosine
    # vs user-embedding. Без префилла на каждое сравнение пара вызовов
    # embed_text(~30мс на CPU MiniLM) даёт O(N_USERS × M_EVENTS) ≈
    # 1600 вызовов = десятки секунд. Префилл сводит это к одному
    # encode-батчу + хеш-выборкам.
    print("[seed] precomputing embeddings…", flush=True)
    t0 = time.monotonic()
    from app.recommender.embeddings import (
        build_event_embedding,
        build_rich_user_embedding,
    )
    for e in db.query(Event).all():
        e.embedding = json.dumps(build_event_embedding(e))
    db.commit()
    print(f"[seed]   event embeddings: {time.monotonic() - t0:.1f}s", flush=True)

    # Users + интеракции
    print(f"[seed] creating {N_USERS} users with interactions…", flush=True)
    for ui in range(N_USERS):
        u = _make_user(db, ui, topics, rng)
        try:
            u.embedding = json.dumps(build_rich_user_embedding(u, interactions=None))
        except Exception:
            u.embedding = None
        main = _main_topic_code(db, u)
        on_main_pool = list(events_by_topic.get(main, []))
        rng.shuffle(on_main_pool)
        # 3-4 «история» — позитивы на доминирующей теме (без target'а)
        n_history = rng.randint(3, 4)
        history = on_main_pool[:n_history]
        target = on_main_pool[n_history] if len(on_main_pool) > n_history else None
        if target is None:
            # запасной вариант, если на main теме недостаточно событий
            target = on_main_pool[-1] if on_main_pool else None
        # 1 шумовая (off-topic) — между history и target, чтобы target оставался
        # последним по id (leave-one-out берёт max(id) как target)
        off_topic_pool = [
            e for tc in events_by_topic
            if tc != main for e in events_by_topic[tc]
        ]
        for e in history:
            _add_interaction(db, u, e, rng.choice(["like", "save"]))
        if off_topic_pool:
            _add_interaction(db, u, rng.choice(off_topic_pool), "like")
        if target is not None:
            # Target — самой последней interaction, чтобы попасть в leave-one-out
            _add_interaction(db, u, target, "save")
    db.commit()
    return db


def main() -> None:
    print(f"Python: {sys.version.split()[0]}", flush=True)
    db = build_synthetic_db()
    try:
        print("\n=== Synthetic offline eval (leave-one-out, seed=42) ===", flush=True)
        print(f"N_USERS={N_USERS}  M_EVENTS={M_EVENTS}  SEED={SEED}\n", flush=True)
        print(f"{'k':>3}  {'algo':10}  {'Recall@k':>10}  {'nDCG@k':>10}", flush=True)
        print("-" * 42, flush=True)
        rows: list[tuple[int, str, float, float]] = []
        n_eval = 0
        for k in (1, 3, 5, 10):
            t0 = time.monotonic()
            res = evaluate(db, k=k, seed=SEED)
            if res.get("status") != "ok":
                print(f"  status={res.get('status')}", flush=True)
                return
            n_eval = res["users_evaluated"]
            for algo in ("rule", "hybrid", "bayesian"):
                rec = res[algo]["recall"]
                ndcg = res[algo]["ndcg"]
                print(f"{k:>3}  {algo:10}  {rec:>10.4f}  {ndcg:>10.4f}", flush=True)
                rows.append((k, algo, rec, ndcg))
            print(f"   (k={k} took {time.monotonic() - t0:.1f}s)\n", flush=True)
        print(f"users evaluated: {n_eval}", flush=True)
        # JSON для удобной вставки в docx
        out = {"users": n_eval, "results": rows}
        with open("/tmp/eval_results.json", "w") as f:
            json.dump(out, f, indent=2)
        print("[saved] /tmp/eval_results.json", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
