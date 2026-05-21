from typing import TypedDict, List, Dict, Any, Literal, Optional


# Закрытый набор intent'ов — синхронизирован с supervisor.SupervisorDecision и
# routing'ом в main графе.
Intent = Literal["recommend", "career", "roadmap", "explain", "summary"]


class CopilotState(TypedDict, total=False):
    # Входы
    goal: str
    telegram_id: int
    db: Any                  # sqlalchemy Session
    k: int                   # retrieved-окно (для специалистов, которые ищут)
    limit: int               # сколько событий рекомендовать на выходе
    history: List[Dict[str, Any]]  # multi-turn: [{role, content, ...}, ...]

    # Заполняется supervisor-нодой
    intent: Intent
    routing_reason: str
    target_event_id: Optional[int]   # для intent=explain
    horizon_months: Optional[int]    # для intent=roadmap

    # Заполняется retrieve/специалистами
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]
    interaction_context: Dict[str, Any]

    # Planner-Critic loop (только для специалистов, у которых это уместно)
    draft_plan: str
    critique_text: str
    revision_count: int

    # Финальный выход
    answer: str
    recommended_event_ids: List[int]
    tool_calls_log: List[Dict[str, Any]]
    specialist: str   # имя ноды, которая дала ответ (для трассировки)
