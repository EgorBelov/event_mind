from typing import Any, TypedDict


class RecommendationState(TypedDict):
    user_profile: dict[str, Any]
    events: list[dict[str, Any]]

    user_analysis: str
    events_analysis: str
    ranked_event_ids: list[dict[str, Any]]  # [{event_id, score, reason}, ...]
    ranked_cards: list[dict[str, Any]]
    final_answer: str