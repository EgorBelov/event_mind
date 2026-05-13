from typing import TypedDict, List, Dict, Any


class CopilotState(TypedDict):
    goal: str
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]
    interaction_summary: str   # краткая текстовая сводка истории взаимодействий пользователя
    answer: str
    recommended_event_ids: List[int]
