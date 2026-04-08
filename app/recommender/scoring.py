from app.recommender.user_model import parse_topics, parse_topic_weights


def score_event_for_user(user, event) -> int:
    score = 0

    user_topics = parse_topics(user.topics)
    event_topics = parse_topics(event.topics)
    topic_weights = parse_topic_weights(user.topic_weights)

    # 1. Тематическое совпадение по весам
    for topic in event_topics:
        score += topic_weights.get(topic, 0)

    # 2. Бонус за явное пересечение тем
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