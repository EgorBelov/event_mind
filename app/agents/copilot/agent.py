"""AI Event Copilot — однонодовый LangGraph-агент.

На вход — цель пользователя + его профиль + список событий. Copilot:
1. Анализирует цель в контексте профиля.
2. Выбирает наиболее релевантные события.
3. Возвращает дружелюбный roadmap/план с рекомендациями.
"""
import json
import re

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

from app.agents.recommendation.llm import llm
from app.agents.copilot.state import CopilotState


_SYSTEM_PROMPT = """
Ты AI Event Copilot — умный помощник по выбору IT-событий.

Твоя задача:
1. Понять цель пользователя.
2. Учесть его профиль: темы, предпочтения, историю взаимодействий.
3. Подобрать подходящие события из списка.
4. Составить краткий план/roadmap: какие события посетить и в каком порядке.
5. Объяснить, почему каждое событие поможет в достижении цели.

Стиль: дружелюбный, конкретный, Telegram-friendly.
Без лишней воды и академизма.

В конце обязательно верни JSON с ID рекомендованных событий в формате:
RECOMMENDED_IDS: [id1, id2, id3]
"""

_USER_PROMPT = """
Цель пользователя: {goal}

Профиль пользователя:
{user_profile}

История взаимодействий:
{interaction_summary}

Доступные события (используй только id из этого списка):
{events}

Составь план и порекомендуй события.
В конце добавь строку: RECOMMENDED_IDS: [id1, id2, ...]
"""


def _parse_recommended_ids(text: str, valid_ids: set[int]) -> list[int]:
    match = re.search(r"RECOMMENDED_IDS:\s*\[([^\]]*)\]", text)
    if not match:
        return []
    try:
        ids = [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]
        return [i for i in ids if i in valid_ids]
    except Exception:
        return []


def copilot_node(state: CopilotState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("user", _USER_PROMPT),
    ])

    result = llm.invoke(
        prompt.format_messages(
            goal=state["goal"],
            user_profile=json.dumps(state["user_profile"], ensure_ascii=False),
            interaction_summary=state.get("interaction_summary", "нет данных"),
            events=json.dumps(state["events"], ensure_ascii=False),
        )
    )

    valid_ids = {e["id"] for e in state["events"]}
    recommended_ids = _parse_recommended_ids(result.content, valid_ids)

    # Вырезаем строку RECOMMENDED_IDS из текста, который покажем пользователю
    answer = re.sub(r"RECOMMENDED_IDS:.*", "", result.content).strip()

    return {
        "answer": answer,
        "recommended_event_ids": recommended_ids,
    }


def _build_copilot_graph():
    graph = StateGraph(CopilotState)
    graph.add_node("copilot", copilot_node)
    graph.add_edge(START, "copilot")
    graph.add_edge("copilot", END)
    return graph.compile()


copilot_graph = _build_copilot_graph()
