from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.recommendation.state import RecommendationState


def user_profile_agent(state: RecommendationState):
    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты UserProfileAgent.
Твоя задача — проанализировать пользователя для системы рекомендаций IT-событий.
Пиши кратко, но содержательно.
"""),
        ("user", """
Профиль пользователя:
{user_profile}

Проанализируй:
1. основные интересы
2. любимые форматы событий
3. что лучше не рекомендовать
4. какой стиль рекомендаций ему подойдет
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            user_profile=state["user_profile"]
        )
    )

    return {
        "user_analysis": result.content
    }