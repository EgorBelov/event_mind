"""Детерминированный синтетический датасет для leave-one-out эвала (seed=42).

Идея из `legacy/scripts/eval_offline_synthetic.py`, но без БД/MiniLM: эмбеддинги
строятся из «тематических» единичных векторов + шум, так что cosine несёт сигнал,
а прогон занимает миллисекунды и полностью воспроизводим.

Схема генерации на пользователя:
- 1 доминирующая тема (вес 10) + с вероятностью 0.6 побочная (вес 3);
- история: 3-4 позитива (like/save) по событиям доминирующей темы;
- 1 «шумовой» позитив по чужой теме (реалистичный шум);
- **target**: ещё одно событие доминирующей темы, скрытое (leave-one-out).
Кандидатский пул = все события, КРОМЕ истории и шума (target включён).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from eventmind.domain.recommender.bayesian import PRIOR_ALPHA, PRIOR_BETA, feedback_delta
from eventmind.domain.recommender.scoring import EventFeatures, UserContext

TOPICS = [
    "ai_ml", "backend", "frontend", "devops",
    "data_science", "cybersecurity", "product", "mobile",
    "cloud", "databases", "golang", "rust",
    "gamedev", "blockchain", "qa_testing", "embedded",
]
FORMATS = ["online", "offline", "hybrid"]
CITIES = ["moscow", "spb", "any"]
DIM = 24
N_USERS = 40
N_EVENTS = 160

BayesianStats = dict[str, tuple[float, float]]


@dataclass(slots=True)
class EvalUser:
    context: UserContext
    stats: BayesianStats
    target_event_id: int
    candidate_ids: list[int]


@dataclass(slots=True)
class Dataset:
    events: list[EventFeatures]
    event_embeddings: dict[int, list[float]]
    users: list[EvalUser]

    @property
    def events_by_id(self) -> dict[int, EventFeatures]:
        return {e.id: e for e in self.events}


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _topic_vectors(rng: random.Random) -> dict[str, list[float]]:
    return {t: _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)]) for t in TOPICS}


def _noisy(base: list[float], rng: random.Random, scale: float = 0.15) -> list[float]:
    return _unit([x + rng.gauss(0.0, scale) for x in base])


def build_dataset(seed: int = 42) -> Dataset:
    rng = random.Random(seed)
    topic_vecs = _topic_vectors(rng)

    # ── события: каждое привязано к одной теме ────────────────────────────────
    events: list[EventFeatures] = []
    embeddings: dict[int, list[float]] = {}
    events_by_topic: dict[str, list[int]] = {t: [] for t in TOPICS}
    for i in range(1, N_EVENTS + 1):
        topic = TOPICS[i % len(TOPICS)]
        emb = _noisy(topic_vecs[topic], rng)
        ev = EventFeatures(
            id=i,
            topics=[topic],
            format=rng.choice(FORMATS),
            city=rng.choice(CITIES),
            quality_score=rng.randint(4, 9),
            hype_score=rng.randint(1, 8),
            embedding=emb,
        )
        events.append(ev)
        embeddings[i] = emb
        events_by_topic[topic].append(i)

    # ── пользователи + интеракции + leave-one-out target ──────────────────────
    users: list[EvalUser] = []
    for _ in range(N_USERS):
        main = rng.choice(TOPICS)
        interests = {main}
        weights = {main: 10}
        if rng.random() < 0.6:
            side = rng.choice([t for t in TOPICS if t != main])
            interests.add(side)
            weights[side] = 3

        pool = list(events_by_topic[main])
        rng.shuffle(pool)
        if len(pool) < 5:
            continue
        n_history = rng.randint(3, 4)
        history = pool[:n_history]
        target = pool[n_history]

        # bayesian-статистики из истории (позитивы) + шумовой негатив-ish позитив
        stats: BayesianStats = {}
        for _ in history:
            _accumulate(stats, [main], rng.choice(["like", "save"]))
        off_topics = [t for t in TOPICS if t != main]
        _accumulate(stats, [rng.choice(off_topics)], "like")

        user_emb = _unit(
            [sum(c) for c in zip(*(topic_vecs[t] for t in interests), strict=True)]
        )
        context = UserContext(
            topics=interests,
            topic_weights=weights,
            preferred_format=rng.choice(FORMATS),
            city=rng.choice(CITIES),
            embedding=user_emb,
        )
        consumed = set(history)
        candidate_ids = [e.id for e in events if e.id not in consumed]
        users.append(
            EvalUser(
                context=context,
                stats=stats,
                target_event_id=target,
                candidate_ids=candidate_ids,
            )
        )

    return Dataset(events=events, event_embeddings=embeddings, users=users)


def _accumulate(stats: BayesianStats, topics: list[str], action: str) -> None:
    d_alpha, d_beta = feedback_delta(action)
    for code in topics:
        a, b = stats.get(code, (PRIOR_ALPHA, PRIOR_BETA))
        stats[code] = (a + d_alpha, b + d_beta)
