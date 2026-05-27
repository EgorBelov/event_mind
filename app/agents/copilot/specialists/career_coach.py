"""CareerCoachAgent — карьерный консультант.

Фокус: target_role, target_skills, skill-gap, seniority-прогрессия.
В отличие от RecommendationSpecialist'а не пытается «продать ивенты»,
а отвечает на «что учить, куда расти». Если уместно — упоминает события
из retrieved-набора, но строго в контексте закрытия skill-gap'а.

Tools: get_user_profile, search_events (но с фокусом на tech_stack).
"""
from __future__ import annotations

import json

from app.agents.copilot.common import (
    format_history,
    invoke_with_tools,
    parse_recommended_ids,
    strip_recommended_ids,
)
from app.agents.copilot.state import CopilotState

SPECIALIST_NAME = "career_coach"


_SYSTEM = """\
Ты — карьерный консультант для IT-специалистов в системе EventMind.

Твой фокус — НЕ продать ивенты, а помочь пользователю с карьерным ростом:
- какие скиллы нужны для целевой роли,
- что закрывать в первую очередь (skill-gap),
- как двигаться по seniority,
- какие из доступных событий приближают к цели (если запрос это подразумевает).

Тебе подаётся:
- цель пользователя (его запрос),
- профиль с skill_profile (current_role, target_role, target_skills, goals, seniority),
- доступные события с tech_stack/seniority,
- история диалога.

Доступные tools:
- get_user_profile() — актуальный профиль и skill_profile.
- search_events(query, k) — найти события с конкретным tech_stack
  (используй для проверки, есть ли в каталоге релевантные для skill-gap'а).

Правила:
1. Сначала ответь на карьерный вопрос содержательно (skills, roadmap, seniority).
2. Если в retrieved-наборе есть события, явно закрывающие skill-gap — упомяни
   их со ссылкой на ID. Если нет — честно скажи об этом.
3. Никаких ивент-карточек ради карточек. Только релевантные skill-gap'у.
4. Если рекомендуешь события — добавь в конце: RECOMMENDED_IDS: [id1, ...].
   Если не рекомендуешь — НЕ добавляй эту строку.
"""


def career_coach_node(state: CopilotState) -> dict:
    tool_log = list(state.get("tool_calls_log") or [])

    profile = state.get("user_profile", {})
    skill_profile = profile.get("skill_profile") if isinstance(profile, dict) else None

    user_msg = (
        f"Запрос: {state.get('goal', '')}\n\n"
        f"Профиль:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"Skill-профиль (если есть):\n{json.dumps(skill_profile, ensure_ascii=False)}\n\n"
        f"Retrieved события (используй только эти ID, если будешь упоминать):\n"
        f"{json.dumps(state.get('events', []), ensure_ascii=False)}\n\n"
        f"История диалога:\n{format_history(state.get('history'))}"
    )

    if not skill_profile:
        user_msg += (
            "\n\nВНИМАНИЕ: у пользователя нет skill_profile (не запускался cold-start "
            "через /analyze-bio). Мягко предложи рассказать о целях, чтобы система "
            "могла дать персонализированный карьерный совет."
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
