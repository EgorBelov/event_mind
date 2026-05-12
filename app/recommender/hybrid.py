"""Hybrid score: rule-based score blended with embedding-based similarity."""

import json

from app.recommender.scoring import score_event_for_user, _get_user_topic_codes
from app.recommender.user_model import parse_topic_weights


def hybrid_score(user, event) -> float:
    rule = score_event_for_user(user, event)

    try:
        # Lazy import — sentence-transformers may not be installed.
        from app.recommender.embeddings import (
            cosine_similarity,
            build_user_embedding,
            build_event_embedding,
        )

        user_topics = list(_get_user_topic_codes(user))
        weights = parse_topic_weights(user.topic_weights)
        user_emb = build_user_embedding(user_topics, weights)

        event_emb_raw = getattr(event, "embedding", None)
        if event_emb_raw:
            try:
                event_emb = json.loads(event_emb_raw)
            except Exception:
                event_emb = build_event_embedding(event)
        else:
            event_emb = build_event_embedding(event)

        sim = cosine_similarity(user_emb, event_emb)
        # Blend: rule contributes ~50%, embedding cosine scaled to 0..10.
        return float(rule) * 0.5 + sim * 10.0
    except Exception:
        return float(rule)
