"""AI Event Copilot — Supervisor-Worker multi-agent граф.

Pipeline:
  retrieve → supervisor → conditional edge to one of specialists:
    ├── recommendation_specialist  (intent=recommend)
    ├── career_coach               (intent=career)
    ├── roadmap_planner            (intent=roadmap)
    ├── event_explainer            (intent=explain)
    └── summary_specialist         (intent=summary)
  → finalize → END

Каждый специалист — отдельная нода со своим system-prompt'ом и подмножеством
function-calling tools. Supervisor классифицирует входящий запрос в один из
intent'ов через структурированный LLM-вызов (pydantic-валидация + keyword
fallback при сбое).

Backward compatibility: интерфейс copilot_graph.invoke({...}) сохранён.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.copilot.specialists import (
    career_coach_node,
    event_explainer_node,
    recommendation_specialist_node,
    roadmap_planner_node,
    summary_specialist_node,
)
from app.agents.copilot.state import CopilotState
from app.agents.copilot.supervisor import route_after_supervisor, supervisor_node

# ─── Pre-supervisor retrieve (общий для всех специалистов) ───────────────


def retrieve_node(state: CopilotState) -> dict:
    """Общая retrieve-нода. Все специалисты получают одинаковый retrieved-набор
    и срез истории. Если специалист сам решит, что нужно ещё — он вызовет
    `search_events` tool.
    """
    from app.agents.copilot.common import build_user_profile_snapshot
    from app.db.models.user import User
    from app.recommender.retrieval import build_interaction_context, retrieve_events_for_query

    db = state["db"]
    user = db.query(User).filter(User.telegram_id == state["telegram_id"]).first()
    if not user:
        return {
            "events": [],
            "interaction_context": {"summary": "профиль не найден", "liked": [], "saved": [], "disliked": []},
            "user_profile": {},
            "tool_calls_log": [],
        }

    k = int(state.get("k") or 10)
    retrieved = retrieve_events_for_query(db, user, state.get("goal", ""), k=k)
    interaction_ctx = build_interaction_context(db, user)
    profile = build_user_profile_snapshot(db, user)

    return {
        "events": retrieved,
        "interaction_context": interaction_ctx,
        "user_profile": profile,
        "tool_calls_log": [],
    }


# ─── Finalize ────────────────────────────────────────────────────────────


def finalize_node(state: CopilotState) -> dict:
    """Финальная нода: проверяет, что answer и recommended_event_ids заполнены."""
    return {
        "answer": state.get("answer") or "",
        "recommended_event_ids": state.get("recommended_event_ids") or [],
        "specialist": state.get("specialist") or "unknown",
    }


# ─── Build graph ─────────────────────────────────────────────────────────


def _build_copilot_graph():
    g = StateGraph(CopilotState)

    g.add_node("retrieve", retrieve_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("recommendation_specialist", recommendation_specialist_node)
    g.add_node("career_coach", career_coach_node)
    g.add_node("roadmap_planner", roadmap_planner_node)
    g.add_node("event_explainer", event_explainer_node)
    g.add_node("summary_specialist", summary_specialist_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "recommendation_specialist": "recommendation_specialist",
            "career_coach": "career_coach",
            "roadmap_planner": "roadmap_planner",
            "event_explainer": "event_explainer",
            "summary_specialist": "summary_specialist",
        },
    )
    for specialist in (
        "recommendation_specialist", "career_coach", "roadmap_planner",
        "event_explainer", "summary_specialist",
    ):
        g.add_edge(specialist, "finalize")
    g.add_edge("finalize", END)
    return g.compile()


copilot_graph = _build_copilot_graph()
