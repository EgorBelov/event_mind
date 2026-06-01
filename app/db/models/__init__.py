"""ORM-модели проекта.

Re-export'ы используются, чтобы Alembic при `from app.db.models import *`
видел все модели и подхватил их metadata для автогенерации миграций.
"""
from .copilot_session import CopilotSession
from .event import Event
from .interaction import Interaction
from .raw_event import RawEvent
from .recommendation_cache import RecommendationCache
from .topic import EventTopic, Topic, UserTopic
from .user import User
from .user_bandit_state import UserBanditState
from .user_memory import UserMemory
from .user_skill_profile import UserSkillProfile
from .user_topic_stat import UserTopicStat

__all__ = [
    "CopilotSession",
    "Event",
    "EventTopic",
    "Interaction",
    "RawEvent",
    "RecommendationCache",
    "Topic",
    "User",
    "UserBanditState",
    "UserMemory",
    "UserSkillProfile",
    "UserTopic",
    "UserTopicStat",
]
