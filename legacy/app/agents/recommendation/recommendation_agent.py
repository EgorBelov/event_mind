import json
import re

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

Верни ТОЛЬКО JSON-массив из топ-3 событий. Никакого другого текста до или после.

Формат:
[
  {{"event_id": <id числом>, "score": <число от 1 до 10>, "reason": "<краткая причина на русском>"}},
  {{"event_id": <id числом>, "score": <число от 1 до 10>, "reason": "<краткая причина на русском>"}},
  {{"event_id": <id числом>, "score": <число от 1 до 10>, "reason": "<краткая причина на русском>"}}
]
"""),
        ("user", """
Анализ пользователя:
{user_analysis}

Анализ событий:
{events_analysis}

Исходный список событий (используй точные id из этого списка):
{events}

Верни JSON-массив топ-3 событий.
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            user_analysis=state["user_analysis"],
            events_analysis=state["events_analysis"],
            events=state["events"],
        )
    )

    ranked_event_ids = _parse_ranked_events(result.content, state["events"])
    return {"ranked_event_ids": ranked_event_ids}


def _parse_ranked_events(text: str, events: list) -> list:
    try:
        text = text.strip()
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            valid_ids = {e["id"] for e in events}
            return [
                item for item in parsed
                if isinstance(item, dict)
                and isinstance(item.get("event_id"), int)
                and item["event_id"] in valid_ids
            ]
    except (json.JSONDecodeError, Exception):
        pass
    return []
