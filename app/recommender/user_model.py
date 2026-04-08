import json


DEFAULT_TOPIC_WEIGHT = 3
LIKE_BONUS = 3
SAVE_BONUS = 1
DISLIKE_PENALTY = 2
MIN_TOPIC_WEIGHT = 0


def parse_topics(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_topic_weights(value: str | None) -> dict[str, int]:
    if not value:
        return {}

    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}

    result: dict[str, int] = {}
    for key, raw_value in data.items():
        try:
            result[key] = int(raw_value)
        except (TypeError, ValueError):
            continue

    return result


def dump_topic_weights(weights: dict[str, int]) -> str:
    return json.dumps(weights, ensure_ascii=False)


def build_initial_topic_weights(topics: list[str]) -> dict[str, int]:
    return {topic: DEFAULT_TOPIC_WEIGHT for topic in topics}


def apply_feedback_to_weights(
    current_weights: dict[str, int],
    event_topics: list[str],
    action: str,
) -> dict[str, int]:
    weights = dict(current_weights)

    for topic in event_topics:
        current_value = weights.get(topic, 0)

        if action == "like":
            weights[topic] = current_value + LIKE_BONUS
        elif action == "save":
            weights[topic] = current_value + SAVE_BONUS
        elif action == "dislike":
            weights[topic] = max(MIN_TOPIC_WEIGHT, current_value - DISLIKE_PENALTY)

    return weights