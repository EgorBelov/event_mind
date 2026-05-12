"""Vector embeddings backed by sentence-transformers.

The heavy model is created on first use of get_model().
If sentence-transformers is not available, callers should catch exceptions and fall back.
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


def build_user_embedding(user_topics: list[str], topic_weights: dict) -> list[float]:
    """Basic user embedding from topic descriptions + weights."""
    parts = [f"{t}: {topic_weights.get(t, 1)}" for t in user_topics]
    text = " ".join(parts) if parts else "general technology events"
    return embed_text(text)


def build_rich_user_embedding(user, interactions: list | None = None) -> list[float]:
    """Richer user embedding: topic weights + city/format preference + interaction history.

    Falls back to basic topic embedding if any step fails.
    """
    from app.recommender.scoring import _get_user_topic_codes
    from app.recommender.user_model import parse_topic_weights
    from app.core.topics import TOPIC_TITLES

    user_topics = list(_get_user_topic_codes(user))
    weights = parse_topic_weights(user.topic_weights)

    parts: list[str] = []

    if user_topics:
        parts.append(
            " ".join(f"{TOPIC_TITLES.get(t, t)} (интерес {weights.get(t, 1):.0f})" for t in user_topics)
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
    """Return cached user embedding from DB or compute a fresh one."""
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
    """Return cached event embedding or compute on the fly."""
    cached = getattr(event, "embedding", None)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return build_event_embedding(event)
