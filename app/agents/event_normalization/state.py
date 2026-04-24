from typing import TypedDict, Dict, Any


class EventNormalizationState(TypedDict):
    raw_event: Dict[str, Any]
    normalized_event: Dict[str, Any]