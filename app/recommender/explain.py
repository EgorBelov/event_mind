from app.recommender.user_model import parse_topic_weights
from app.recommender.scoring import _get_user_topic_codes, _get_event_topic_codes
from app.core.topics import topic_title, format_label


def explain_event_for_user(user, event, db=None) -> str:
    """Вернуть человекочитаемое объяснение (под Telegram)."""
    result = explain_event_detailed(user, event, db=db)
    return result["text"]


def explain_event_detailed(user, event, db=None) -> dict:
    """Вернуть структурированное объяснение: текст + детали.

    Ключи:
        text (str): человекочитаемое объяснение.
        topic_match (list[str]): совпавшие коды тем.
        format_match (bool): совпадение формата.
        city_match (bool): совпадение города.
        semantic_similarity (float | None): cosine-сходство, если посчитано.
        history_signals (list[str]): причины из истории взаимодействий.
    """
    reasons: list[str] = []
    details: dict = {
        "topic_match": [],
        "format_match": False,
        "city_match": False,
        "semantic_similarity": None,
        "history_signals": [],
    }

    user_topics = _get_user_topic_codes(user)
    event_topics = _get_event_topic_codes(event)
    topic_weights = parse_topic_weights(user.topic_weights)

    common_topics = list(user_topics.intersection(event_topics))
    details["topic_match"] = common_topics
    if common_topics:
        names = [topic_title(t) for t in common_topics]
        reasons.append(f"темы: {', '.join(names)}")

    weighted = [t for t in event_topics if topic_weights.get(t, 0) > 3]
    if weighted:
        names = [topic_title(t) for t in weighted]
        reasons.append(f"высокий интерес: {', '.join(names)}")

    if user.preferred_format and user.preferred_format == event.format:
        details["format_match"] = True
        reasons.append(f"формат ({format_label(event.format)})")
    elif getattr(user, "preferred_format", None) == "any":
        reasons.append("любой формат")

    if user.city and user.city == event.city:
        details["city_match"] = True
        reasons.append("совпадает город")
    elif user.city == "any" or event.city == "any":
        reasons.append("нет ограничения по городу")

    # Семантическое сходство (best-effort)
    try:
        from app.recommender.embeddings import (
            get_or_build_user_embedding,
            get_or_build_event_embedding,
            cosine_similarity,
        )
        user_emb = get_or_build_user_embedding(user)
        event_emb = get_or_build_event_embedding(event)
        sim = round(cosine_similarity(user_emb, event_emb), 3)
        details["semantic_similarity"] = sim
        if sim >= 0.5:
            reasons.append(f"семантически близко (сходство {sim:.2f})")
    except Exception:
        pass

    if db is not None:
        try:
            history = _explain_from_interactions(user, event, db)
            details["history_signals"] = history
            reasons.extend(history)
        except Exception:
            pass

    text = "Почему рекомендовано: " + "; ".join(reasons) if reasons else "Подобрано по базовому совпадению профиля."
    details["text"] = text
    return details


def _explain_from_interactions(user, event, db) -> list[str]:
    from app.db.models.interaction import Interaction
    from app.db.models.event import Event

    reasons: list[str] = []
    event_topics = _get_event_topic_codes(event)

    interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
    if not interactions:
        return reasons

    liked_ids = {i.event_id for i in interactions if i.action == "like"}
    saved_ids = {i.event_id for i in interactions if i.action == "save"}

    liked_topics: set[str] = set()
    saved_topics: set[str] = set()
    liked_formats: dict[str, int] = {}

    related_ids = list(liked_ids | saved_ids)
    if related_ids:
        for e in db.query(Event).filter(Event.id.in_(related_ids)).all():
            topics = _get_event_topic_codes(e)
            if e.id in liked_ids:
                liked_topics.update(topics)
                liked_formats[e.format] = liked_formats.get(e.format, 0) + 1
            if e.id in saved_ids:
                saved_topics.update(topics)

    if saved_match := saved_topics.intersection(event_topics):
        names = [topic_title(t) for t in saved_match]
        reasons.append(f"сохранял похожие темы: {', '.join(names)}")

    if liked_match := liked_topics.intersection(event_topics) - saved_match:
        names = [topic_title(t) for t in liked_match]
        reasons.append(f"лайкал похожие темы: {', '.join(names)}")

    if liked_formats:
        top_fmt = max(liked_formats, key=liked_formats.get)
        if event.format == top_fmt and liked_formats[top_fmt] >= 2:
            reasons.append(f"любит {format_label(event.format)}-формат")

    return reasons
