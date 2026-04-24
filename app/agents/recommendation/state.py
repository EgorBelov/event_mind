from typing import TypedDict, List, Dict, Any


class RecommendationState(TypedDict):
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]

    user_analysis: str
    events_analysis: str
    ranked_events: str
    final_answer: str