"""Векторные embedding'и на базе sentence-transformers.

Тяжёлая модель создаётся при первом вызове get_model().
Если sentence-transformers недоступен, вызывающий код должен перехватить
исключение и плавно деградировать.
"""

import json

import numpy as np

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def embed_text(text: str) -> list[float]:
    return get_model().encode(text).tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-9)
    return float(np.dot(a_arr, b_arr) / denom)


def build_session_embedding(db, user, window: int = 5) -> list[float] | None:
    """Эмбеддинг последних `window` взаимодействий пользователя.

    Усреднение эмбеддингов событий с весами:
        like  → +1.0
        save  → +1.5
        dislike → −0.7  (вычитается; «не хочу про X»)

    Возвращает None при отсутствии истории или сбое.
    """
    from app.db.models.interaction import Interaction
    from app.db.models.event import Event
    import numpy as np

    weights_per_action = {"like": 1.0, "save": 1.5, "dislike": -0.7}

    try:
        rows = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id)
            .order_by(Interaction.id.desc())
            .limit(window)
            .all()
        )
        if not rows:
            return None
        event_ids = [r.event_id for r in rows]
        events_map = {e.id: e for e in db.query(Event).filter(Event.id.in_(event_ids)).all()}

        vecs = []
        weights = []
        for r in rows:
            ev = events_map.get(r.event_id)
            if ev is None or not ev.embedding:
                continue
            try:
                vecs.append(np.array(json.loads(ev.embedding)))
                weights.append(weights_per_action.get(r.action, 0.0))
            except Exception:
                continue
        if not vecs:
            return None
        w = np.array(weights).reshape(-1, 1)
        total = (np.array(vecs) * w).sum(axis=0)
        norm = np.linalg.norm(total)
        if norm < 1e-9:
            return None
        return (total / norm).tolist()
    except Exception:
        return None


def blend_user_embedding(
    long_term: list[float],
    session: list[float] | None,
    session_weight: float = 0.3,
) -> list[float]:
    """Линейная комбинация long-term и сессионного эмбеддинга, нормализованная."""
    import numpy as np
    if session is None:
        return long_term
    a = np.array(long_term)
    b = np.array(session)
    mixed = (1.0 - session_weight) * a + session_weight * b
    norm = np.linalg.norm(mixed)
    if norm < 1e-9:
        return long_term
    return (mixed / norm).tolist()


def build_rich_user_embedding(user, interactions: list | None = None) -> list[float]:
    """Расширенный embedding: веса тем + город/формат + история взаимодействий.

    При сбое на любом шаге откатывается к базовому embedding'у по темам.
    """
    from app.recommender.scoring import _get_user_topic_codes
    from app.recommender.user_model import parse_topic_weights
    from app.core.topics import topic_title

    user_topics = list(_get_user_topic_codes(user))
    weights = parse_topic_weights(user.topic_weights)

    parts: list[str] = []

    if user_topics:
        parts.append(
            " ".join(f"{topic_title(t)} (интерес {weights.get(t, 1):.0f})" for t in user_topics)
        )

    if user.preferred_format and user.preferred_format not in ("any", "unknown"):
        parts.append(f"предпочитает {user.preferred_format} события")

    if user.city and user.city not in ("any", "unknown"):
        parts.append(f"город {user.city}")

    if interactions:
        liked = sum(1 for i in interactions if i.action == "like")
        saved = sum(1 for i in interactions if i.action == "save")
        if liked or saved:
            parts.append(f"активен: {liked} лайков, {saved} сохранений")

    text = "; ".join(parts) if parts else "разработчик IT"
    return embed_text(text)


def get_or_build_user_embedding(user, interactions: list | None = None) -> list[float]:
    """Вернуть закэшированный embedding пользователя из БД или посчитать новый."""
    cached = getattr(user, "embedding", None)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return build_rich_user_embedding(user, interactions)


def build_event_embedding(event) -> list[float]:
    text = f"{event.title} {event.description}"
    return embed_text(text)


def get_or_build_event_embedding(event) -> list[float]:
    """Вернуть закэшированный embedding события или посчитать на лету."""
    cached = getattr(event, "embedding", None)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return build_event_embedding(event)


def ensure_event_embeddings(db, events) -> int:
    """Досчитать и СОХРАНИТЬ embedding для событий, у которых его нет.

    Узкое место /recommendations — пересчёт векторов всех событий на каждый
    запрос. Здесь недостающие кодируются одним батчем (а не N вызовами) и
    пишутся в `events.embedding`, после чего запросы попадают в кэш и
    кодирование не повторяется. Возвращает число досчитанных событий.
    """
    missing = [e for e in events if not getattr(e, "embedding", None)]
    if not missing:
        return 0
    try:
        model = get_model()
        texts = [f"{e.title} {e.description}" for e in missing]
        vectors = model.encode(texts)  # один батч вместо N отдельных encode
        for e, vec in zip(missing, vectors):
            e.embedding = json.dumps(vec.tolist())
        db.commit()
        return len(missing)
    except Exception:
        db.rollback()
        return 0
