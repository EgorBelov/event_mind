from app.recommender.user_model import parse_topics, parse_topic_weights


def _get_user_topic_codes(user) -> set[str]:
    """Получить коды тем пользователя. Поддерживает и relationship, и legacy-CSV."""
    if hasattr(user, "user_topics") and user.user_topics is not None:
        try:
            codes = {ut.topic.code for ut in user.user_topics if ut.topic}
            if codes:
                return codes
        except Exception:
            pass
    # Fallback на старый CSV-атрибут, если он есть
    legacy = getattr(user, "topics", None)
    return parse_topics(legacy)


def _get_event_topic_codes(event) -> set[str]:
    """Получить коды тем события. Поддерживает и relationship, и legacy-CSV."""
    if hasattr(event, "event_topics") and event.event_topics is not None:
        try:
            codes = {et.topic.code for et in event.event_topics if et.topic}
            if codes:
                return codes
        except Exception:
            pass
    # Fallback на старый CSV-атрибут, если он есть
    legacy = getattr(event, "topics", None)
    return parse_topics(legacy)


def score_event_for_user(user, event) -> int:
    score = 0

    user_topics = _get_user_topic_codes(user)
    event_topics = _get_event_topic_codes(event)
    topic_weights = parse_topic_weights(user.topic_weights)

    # 1. Совпадение по темам с учётом весов
    for topic in event_topics:
        score += topic_weights.get(topic, 0)

    # 2. Бонус за прямое пересечение тем
    common_topics = user_topics.intersection(event_topics)
    score += len(common_topics) * 2

    # 3. Формат
    if user.preferred_format == "any":
        score += 1
    elif user.preferred_format and user.preferred_format == event.format:
        score += 3

    # 4. Город
    if user.city == "any" or event.city == "any":
        score += 1
    elif user.city and user.city == event.city:
        score += 2

    return score
