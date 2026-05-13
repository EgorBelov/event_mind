from typing import TypedDict, List, Dict, Any


class RecommendationState(TypedDict):
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]

    user_analysis: str
    events_analysis: str
    ranked_event_ids: List[Dict[str, Any]]  # [{event_id, score, reason}, ...]
    ranked_cards: List[Dict[str, Any]]
    final_answer: str