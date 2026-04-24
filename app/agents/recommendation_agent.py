import os
from typing import TypedDict, List, Dict, Any

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate


load_dotenv()


class RecommendationState(TypedDict):
    user_profile: Dict[str, Any]
    events: List[Dict[str, Any]]
    analyzed_user: str
    filtered_events: List[Dict[str, Any]]
    ranked_events: str
    final_answer: str


llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    temperature=0.4,
    max_retries=2,
)


def analyze_user(state: RecommendationState):
    user = state["user_profile"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", "Ты ИИ-агент рекомендаций IT-событий."),
        ("user", """
Проанализируй профиль пользователя.

Профиль:
{user}

Опиши:
1. основные интересы
2. какие события ему подойдут
3. какие события лучше не рекомендовать
""")
    ])

    result = llm.invoke(prompt.format_messages(user=user))

    return {
        "analyzed_user": result.content
    }


def filter_events(state: RecommendationState):
    user = state["user_profile"]
    events = state["events"]

    liked_categories = set(user.get("liked_categories", []))
    disliked_categories = set(user.get("disliked_categories", []))

    filtered = []

    for event in events:
        category = event.get("category")

        if category in disliked_categories:
            continue

        if category in liked_categories:
            event["base_score"] = 2
        else:
            event["base_score"] = 1

        filtered.append(event)

    return {
        "filtered_events": filtered
    }


def rank_events(state: RecommendationState):
    analyzed_user = state["analyzed_user"]
    events = state["filtered_events"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты ИИ-агент рекомендаций.
Твоя задача — выбрать лучшие события для пользователя.
Отвечай структурированно.
"""),
        ("user", """
Анализ пользователя:
{analyzed_user}

Список событий:
{events}

Выбери топ-3 события.
Для каждого события напиши:
- название
- почему подходит пользователю
- оценку от 1 до 10
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            analyzed_user=analyzed_user,
            events=events
        )
    )

    return {
        "ranked_events": result.content
    }


def generate_final_answer(state: RecommendationState):
    ranked_events = state["ranked_events"]

    return {
        "final_answer": ranked_events
    }


def build_recommendation_agent():
    graph = StateGraph(RecommendationState)

    graph.add_node("analyze_user", analyze_user)
    graph.add_node("filter_events", filter_events)
    graph.add_node("rank_events", rank_events)
    graph.add_node("generate_final_answer", generate_final_answer)

    graph.add_edge(START, "analyze_user")
    graph.add_edge("analyze_user", "filter_events")
    graph.add_edge("filter_events", "rank_events")
    graph.add_edge("rank_events", "generate_final_answer")
    graph.add_edge("generate_final_answer", END)

    return graph.compile()


recommendation_agent = build_recommendation_agent()