from app.recommender.user_model import parse_topics, parse_topic_weights


TOPIC_LABELS = {
    "ai_ml": "AI / ML",
    "data_science": "Data Science",
    "business_analytics": "Бизнес-аналитика",
    "backend": "Backend",
    "product": "Product",
}


def explain_event_for_user(user, event) -> str:
    reasons = []

    user_topics = parse_topics(user.topics)
    event_topics = parse_topics(event.topics)
    topic_weights = parse_topic_weights(user.topic_weights)

    common_topics = user_topics.intersection(event_topics)
    if common_topics:
        topic_names = [TOPIC_LABELS.get(topic, topic) for topic in common_topics]
        reasons.append(f"совпадает по выбранным темам: {', '.join(topic_names)}")

    weighted_topics = [topic for topic in event_topics if topic_weights.get(topic, 0) > 3]
    if weighted_topics:
        topic_names = [TOPIC_LABELS.get(topic, topic) for topic in weighted_topics]
        reasons.append(f"учитывает накопленный интерес: {', '.join(topic_names)}")

    if user.preferred_format == event.format:
        reasons.append("подходит по формату")
    elif user.preferred_format == "any":
        reasons.append("формат не ограничен")

    if user.city == event.city:
        reasons.append("подходит по городу")
    elif user.city == "any" or event.city == "any":
        reasons.append("не ограничено по городу")

    if reasons:
        return "Почему рекомендовано: " + "; ".join(reasons)

    return "Подобрано по базовому совпадению профиля."