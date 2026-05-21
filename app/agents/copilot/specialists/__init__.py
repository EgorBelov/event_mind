"""Специалисты multi-agent Copilot'а. Каждый — отдельная LangGraph-нода
с собственным system prompt'ом и подмножеством tools.

Все специалисты:
- получают на вход CopilotState (goal, telegram_id, db, history, user_profile, ...);
- пишут в state: `answer`, `recommended_event_ids`, `specialist`, `tool_calls_log`;
- best-effort: при сбое возвращают fallback-сообщение, но не ломают граф.
"""
from app.agents.copilot.specialists.recommendation import recommendation_specialist_node
from app.agents.copilot.specialists.career_coach import career_coach_node
from app.agents.copilot.specialists.roadmap import roadmap_planner_node
from app.agents.copilot.specialists.explainer import event_explainer_node
from app.agents.copilot.specialists.summary import summary_specialist_node


__all__ = [
    "recommendation_specialist_node",
    "career_coach_node",
    "roadmap_planner_node",
    "event_explainer_node",
    "summary_specialist_node",
]
