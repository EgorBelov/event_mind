from typing import Any, TypedDict


class EventNormalizationState(TypedDict):
    raw_event: dict[str, Any]
    normalized_event: dict[str, Any]