"""RecommendationSpecialist — найти и порекомендовать события под запрос.

Самый «тяжёлый» специалист: использует RAG retrieval, все 4 tools и проходит
через critique-revise loop (унаследовано от старого монолитного копилота).
"""
from __future__ import annotations

import json

from app.agents.copilot.state import CopilotState
from app.agents.copilot.common import (
    invoke_with_tools,
    format_history,
    parse_recommended_ids,
    strip_recommended_ids,
    build_user_profile_snapshot,
)


SPECIALIST_NAME = "recommendation_specialist"
MAX_REVISIONS = 1


_SYSTEM = """\
Ты — специалист по подбору IT-событий в системе EventMind.

Тебе подаётся:
- цель пользователя (его текущий запрос),
- его профиль,
- retrieved-список событий (только из него можно рекомендовать!),
- срез истории,
- история предыдущих turn'ов.

Доступные tools:
- search_events(query, k) — дополнить retrieved-набор уточнённым семантическим поиском.
- get_user_profile() — актуальный профиль.
- get_interactions_summary() — сводка по лайкам/сейвам.
- mark_saved(event_id) — сохранить событие, если пользователь явно попросил.

Правила:
1. Рекомендуй только из retrieved/найденных событий.
2. Не дублируй то, что уже обсуждалось в прошлых turn'ах.
3. Не предлагай события из тем, которые пользователь явно дизлайкнул.
4. Стиль: дружелюбный, конкретный, Telegram-friendly.
5. В конце обязательно: RECOMMENDED_IDS: [id1, id2, ...]
"""


def _plan(state: CopilotState) -> str:
    tool_log = state.get("tool_calls_log") or []
    user_msg = (
        f"Цель: {state.get('goal', '')}\n\n"
        f"Профиль:\n{json.dumps(state.get('user_profile', {}), ensure_ascii=False)}\n\n"
        f"Retrieved события:\n{json.dumps(state.get('events', []), ensure_ascii=False)}\n\n"
        f"История взаимодействий:\n{json.dumps(state.get('interaction_context', {}), ensure_ascii=False)}\n\n"
        f"Предыдущие turn'ы:\n{format_history(state.get('history'))}\n\n"
        f"Подбери до {int(state.get('limit') or 3)} событий + RECOMMENDED_IDS."
    )
    return invoke_with_tools(
        system_prompt=_SYSTEM,
        user_prompt=user_msg,
        db=state["db"],
        telegram_id=state["telegram_id"],
        tool_names=["search_events", "get_user_profile", "get_interactions_summary", "mark_saved", "recall_about_user"],
        tool_log=tool_log,
    )


_CRITIC_SYSTEM = """\
Ты — критик ответа специалиста по рекомендациям. Оцени план по 3 пунктам:
1. Релевантность цели пользователя.
2. Разнообразие тем/уровней/форматов.
3. Учёт истории (избегание дизлайкнутых тем, преемственность с прошлыми turn'ами).

Если план хорош — верни ровно "OK". Иначе — короткая критика (1-3 предложения)
с конкретными правками.
"""


def _critique(plan: str, state: CopilotState) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.agents.recommendation.llm import llm
    msg = (
        f"Цель: {state.get('goal', '')}\n\n"
        f"План:\n{plan}\n\n"
        f"История turn'ов:\n{format_history(state.get('history'))}"
    )
    response = llm.invoke([SystemMessage(content=_CRITIC_SYSTEM), HumanMessage(content=msg)])
    return (response.content or "").strip()


_REVISE_SYSTEM = """\
Ты исправляешь свой предыдущий план рекомендаций по полученной критике.
Сохрани стиль и формат, включая финальную строку RECOMMENDED_IDS.
"""


def _revise(plan: str, critique: str) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.agents.recommendation.llm import llm
    msg = f"Предыдущий план:\n{plan}\n\nКритика:\n{critique}\n\nДай исправленный план полностью."
    response = llm.invoke([SystemMessage(content=_REVISE_SYSTEM), HumanMessage(content=msg)])
    return response.content or ""


def recommendation_specialist_node(state: CopilotState) -> dict:
    tool_log = list(state.get("tool_calls_log") or [])

    # 1. Plan
    plan = _plan({**state, "tool_calls_log": tool_log})

    # 2. Critique → revise loop (до MAX_REVISIONS итераций)
    for _ in range(MAX_REVISIONS):
        critique = _critique(plan, state)
        if critique.upper().startswith("OK"):
            break
        plan = _revise(plan, critique)

    # 3. Finalize
    valid_ids = {e["id"] for e in state.get("events", [])}
    return {
        "answer": strip_recommended_ids(plan),
        "recommended_event_ids": parse_recommended_ids(plan, valid_ids),
        "tool_calls_log": tool_log,
        "specialist": SPECIALIST_NAME,
        "draft_plan": plan,
    }
