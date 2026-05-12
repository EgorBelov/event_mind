"""Vector embeddings backed by sentence-transformers.

Importing this module does NOT load the model — the heavy model is created on
first use of `get_model()`. If sentence-transformers (or the model itself) is
not available, callers can catch the ImportError / RuntimeError and fall back.
"""

import numpy as np

_model = None


def get_model():
    """Lazy-load the multilingual sentence transformer."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def embed_text(text: str) -> list[float]:
    model = get_model()
    return model.encode(text).tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-9)
    return float(np.dot(a_arr, b_arr) / denom)


def build_user_embedding(user_topics: list[str], topic_weights: dict) -> list[float]:
    """Build user embedding from topic descriptions weighted by topic_weights."""
    topic_texts = [f"{t}: {topic_weights.get(t, 1)}" for t in user_topics]
    combined = " ".join(topic_texts) if topic_texts else "general technology events"
    return embed_text(combined)


def build_event_embedding(event) -> list[float]:
    text = f"{event.title} {event.description}"
    return embed_text(text)
