from langgraph.graph import StateGraph, START, END

from app.agents.recommendation.state import RecommendationState
from app.agents.recommendation.user_profile_agent import user_profile_agent
from app.agents.recommendation.event_analyzer_agent import event_analyzer_agent
from app.agents.recommendation.recommendation_agent import recommendation_agent_node
from app.agents.recommendation.explanation_agent import explanation_agent


def build_recommendation_graph():
    graph = StateGraph(RecommendationState)

    graph.add_node("user_profile_agent", user_profile_agent)
    graph.add_node("event_analyzer_agent", event_analyzer_agent)
    graph.add_node("recommendation_agent", recommendation_agent_node)
    graph.add_node("explanation_agent", explanation_agent)

    graph.add_edge(START, "user_profile_agent")
    graph.add_edge("user_profile_agent", "event_analyzer_agent")
    graph.add_edge("event_analyzer_agent", "recommendation_agent")
    graph.add_edge("recommendation_agent", "explanation_agent")
    graph.add_edge("explanation_agent", END)

    return graph.compile()


recommendation_graph = build_recommendation_graph()