from typing import TypedDict, List, Dict, Any


class CopilotState(TypedDict):
    goal: str
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]
    interaction_summary: str   # short text summary of user's interaction history
    answer: str
    recommended_event_ids: List[int]
