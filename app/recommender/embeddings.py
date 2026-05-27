"""Векторные embedding'и на базе sentence-transformers.

Тяжёлая модель создаётся при первом вызове get_model().
Если sentence-transformers недоступен, вызывающий код должен перехватить
исключение и плавно деградировать.

Backend хранения:
- SQLite — JSON-Text-колонка `events.embedding` / `users.embedding`.
- PostgreSQL + pgvector — параллельно используется `embedding_vec vector(384)`,
  которая позволяет делать top-k через оператор `<->` (см. retrieval.py).
  Запись идёт в обе колонки: чтение всё ещё может опереться на JSON, но
  быстрый top-k использует vector-индекс.
"""

import json
import logging

import numpy as np

from app.db.backend import has_pgvector, is_postgres

logger = logging.getLogger(__name__)

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
    import numpy as np

    from app.db.models.event import Event
    from app.db.models.interaction import Interaction

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
    from app.core.topics import topic_title
    from app.recommender.scoring import _get_user_topic_codes
    from app.recommender.user_model import parse_topic_weights

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


def _write_embedding(obj, vec_list: list[float]) -> None:
    """Сохранить embedding в obj.

    - SQLite: только JSON-колонка `embedding`.
    - PostgreSQL+pgvector: дополнительно `embedding_vec` (если колонка
      есть в metadata; иначе тихо пропускается).
    """
    obj.embedding = json.dumps(vec_list)
    if has_pgvector() and hasattr(obj, "embedding_vec"):
        # Колонка может быть ещё не отражена в ORM-модели (миграция не накатана) —
        # JSON-фолбэк уже сделан выше, на этой ветке тихо пропускаем.
        try:
            obj.embedding_vec = vec_list
        except Exception as e:
            logger.debug("embedding_vec write skipped: %s", e)


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
        for e, vec in zip(missing, vectors, strict=True):
            _write_embedding(e, vec.tolist())
        db.commit()
        return len(missing)
    except Exception as e:
        logger.warning("ensure_event_embeddings failed, rollback: %s", e)
        db.rollback()
        return 0


def pgvector_top_k_events(db, query_vec: list[float], k: int = 20) -> list[int]:
    """Top-k event_id по cosine-расстоянию через pgvector (оператор <=>).

    Возвращает [] на SQLite или при отсутствии pgvector — вызывающая сторона
    делает фолбэк на in-process сортировку по cosine_similarity. На PG с
    индексом IVFFlat запрос отрабатывает за миллисекунды даже на сотнях
    тысяч событий.
    """
    if not has_pgvector() or not is_postgres():
        return []
    try:
        from sqlalchemy import text
        # pgvector принимает строковую форму '[v1,v2,...]'.
        vec_str = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"
        sql = text(
            "SELECT id FROM events "
            "WHERE embedding_vec IS NOT NULL "
            "ORDER BY embedding_vec <=> CAST(:q AS vector) "
            "LIMIT :k"
        )
        rows = db.execute(sql, {"q": vec_str, "k": k}).all()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("pgvector_top_k_events failed, returning []: %s", e)
        return []
