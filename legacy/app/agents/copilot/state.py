from typing import Any, Literal, TypedDict

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
    history: list[dict[str, Any]]  # multi-turn: [{role, content, ...}, ...]

    # Заполняется supervisor-нодой
    intent: Intent
    routing_reason: str
    target_event_id: int | None   # для intent=explain
    horizon_months: int | None    # для intent=roadmap

    # Заполняется retrieve/специалистами
    user_profile: dict[str, Any]
    events: list[dict[str, Any]]
    interaction_context: dict[str, Any]

    # Planner-Critic loop (только для специалистов, у которых это уместно)
    draft_plan: str
    critique_text: str
    revision_count: int

    # Финальный выход
    answer: str
    recommended_event_ids: list[int]
    tool_calls_log: list[dict[str, Any]]
    specialist: str   # имя ноды, которая дала ответ (для трассировки)
