from app.recommender.user_model import parse_topic_weights
from app.recommender.scoring import _get_user_topic_codes, _get_event_topic_codes
from app.core.topics import TOPIC_TITLES, FORMAT_LABELS


def explain_event_for_user(user, event, db=None) -> str:
    reasons = []

    user_topics = _get_user_topic_codes(user)
    event_topics = _get_event_topic_codes(event)
    topic_weights = parse_topic_weights(user.topic_weights)

    common_topics = user_topics.intersection(event_topics)
    if common_topics:
        names = [TOPIC_TITLES.get(t, t) for t in common_topics]
        reasons.append(f"совпадает по выбранным темам: {', '.join(names)}")

    weighted_topics = [t for t in event_topics if topic_weights.get(t, 0) > 3]
    if weighted_topics:
        names = [TOPIC_TITLES.get(t, t) for t in weighted_topics]
        reasons.append(f"высокий интерес к теме: {', '.join(names)}")

    if user.preferred_format and user.preferred_format == event.format:
        reasons.append(f"подходит по формату ({FORMAT_LABELS.get(event.format, event.format)})")
    elif getattr(user, "preferred_format", None) == "any":
        reasons.append("формат не ограничен")

    if user.city and user.city == event.city:
        reasons.append("подходит по городу")
    elif user.city == "any" or event.city == "any":
        reasons.append("не ограничено по городу")

    if db is not None:
        try:
            reasons.extend(_explain_from_interactions(user, event, db))
        except Exception:
            pass

    return "Почему рекомендовано: " + "; ".join(reasons) if reasons else "Подобрано по базовому совпадению профиля."


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
        names = [TOPIC_TITLES.get(t, t) for t in saved_match]
        reasons.append(f"ты сохранял события по темам {', '.join(names)} раньше")

    if liked_match := liked_topics.intersection(event_topics) - saved_match:
        names = [TOPIC_TITLES.get(t, t) for t in liked_match]
        reasons.append(f"тебе нравились похожие события по темам {', '.join(names)}")

    if liked_formats:
        top_fmt = max(liked_formats, key=liked_formats.get)
        if event.format == top_fmt and liked_formats[top_fmt] >= 2:
            reasons.append(f"тебе нравятся {FORMAT_LABELS.get(event.format, event.format)}-форматы")

    return reasons
