"""RoadmapPlanner — составить план обучения через sequence событий.

В отличие от RecommendationSpecialist'а:
- учитывает временной горизонт (`horizon_months`),
- располагает события в логической последовательности (начальные → продвинутые),
- группирует по этапам.

Tools: get_user_profile, search_events (для добора если retrieved-набор тонкий).
"""
from __future__ import annotations

import json

from app.agents.copilot.state import CopilotState
from app.agents.copilot.common import (
    invoke_with_tools,
    format_history,
    parse_recommended_ids,
    strip_recommended_ids,
)


SPECIALIST_NAME = "roadmap_planner"


_SYSTEM = """\
Ты — планировщик образовательной траектории для IT-специалистов.

Тебе подаётся:
- цель пользователя (часто включает срок: «за 3 месяца», «до конца года»),
- профиль и skill_profile (current_role → target_role),
- доступные события,
- история диалога.

Доступные tools:
- get_user_profile() — профиль и skill_profile.
- search_events(query, k) — добор событий по конкретному скиллу/теме, если
  retrieved-набор кажется тонким для какого-то этапа.

Правила:
1. Раздели траекторию на 2–4 этапа (например: «Месяц 1: основы», «Месяц 2: углубление», ...).
2. На каждом этапе укажи 1–3 события из retrieved/найденных + что от них взять.
3. Логика — от простого к сложному, от широкого к узкому.
4. Если в каталоге не хватает событий под этап — честно скажи и предложи
   формат самостоятельной подготовки.
5. Стиль: структурированный, по пунктам. Telegram-friendly разметка.
6. В конце: RECOMMENDED_IDS: [id1, id2, ...] — все события, упомянутые в плане.
"""


def roadmap_planner_node(state: CopilotState) -> dict:
    tool_log = list(state.get("tool_calls_log") or [])
    horizon = state.get("horizon_months")
    horizon_str = f"{horizon} месяцев" if horizon else "не указан явно — оцени по контексту"

    user_msg = (
        f"Запрос: {state.get('goal', '')}\n"
        f"Срок плана: {horizon_str}\n\n"
        f"Профиль:\n{json.dumps(state.get('user_profile', {}), ensure_ascii=False)}\n\n"
        f"Retrieved события:\n{json.dumps(state.get('events', []), ensure_ascii=False)}\n\n"
        f"История диалога:\n{format_history(state.get('history'))}\n\n"
        "Составь этапный план + RECOMMENDED_IDS со всеми упомянутыми событиями."
    )

    answer = invoke_with_tools(
        system_prompt=_SYSTEM,
        user_prompt=user_msg,
        db=state["db"],
        telegram_id=state["telegram_id"],
        tool_names=["get_user_profile", "search_events", "recall_about_user"],
        tool_log=tool_log,
    )

    valid_ids = {e["id"] for e in state.get("events", [])}
    return {
        "answer": strip_recommended_ids(answer),
        "recommended_event_ids": parse_recommended_ids(answer, valid_ids),
        "tool_calls_log": tool_log,
        "specialist": SPECIALIST_NAME,
    }
