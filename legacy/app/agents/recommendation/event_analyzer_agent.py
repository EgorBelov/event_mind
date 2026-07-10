from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.recommendation.state import RecommendationState


def event_analyzer_agent(state: RecommendationState):
    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты EventAnalyzerAgent.
Твоя задача — проанализировать список IT-событий.
Для каждого события определи тему, формат, уровень и кому оно подойдет.
"""),
        ("user", """
Список событий:
{events}

Проанализируй события.
Для каждого события напиши:
- название
- основная тема
- формат
- уровень: beginner / middle / advanced
- кому подойдет
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            events=state["events"]
        )
    )

    return {
        "events_analysis": result.content
    }