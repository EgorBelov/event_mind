from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.recommendation.state import RecommendationState


def recommendation_agent_node(state: RecommendationState):
    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты RecommendationAgent.
Твоя задача — сопоставить анализ пользователя и анализ событий.
Выбери наиболее подходящие события.
Не рекомендуй события, которые явно противоречат интересам пользователя.
"""),
        ("user", """
Анализ пользователя:
{user_analysis}

Анализ событий:
{events_analysis}

Исходный список событий:
{events}

Выбери топ-3 события.

Для каждого события укажи:
- место в рейтинге
- название
- оценку релевантности от 1 до 10
- краткую причину выбора
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            user_analysis=state["user_analysis"],
            events_analysis=state["events_analysis"],
            events=state["events"],
        )
    )

    return {
        "ranked_events": result.content
    }