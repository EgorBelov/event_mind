"""SummarySpecialist — нарратизировать историю взаимодействий пользователя.

Самый «лёгкий» специалист: данные уже агрегированы в interaction_context
+ get_interactions_summary tool. Цель — пересказать это разговорным языком
с инсайтами («ты много лайкал DevOps, а Frontend почти не трогал»).

Tools: get_interactions_summary, get_user_profile.
"""
from __future__ import annotations

import json

from app.agents.copilot.common import format_history, invoke_with_tools
from app.agents.copilot.state import CopilotState

SPECIALIST_NAME = "summary_specialist"


_SYSTEM = """\
Ты — аналитик активности пользователя в EventMind.

Твоя задача — рассказать пользователю про его собственную историю
взаимодействий и предпочтения. Не рекомендуй новые события (это не твоя
работа) — только пересказывай и подмечай паттерны.

Тебе подаётся:
- запрос пользователя,
- профиль,
- срез истории (interaction_context: liked/saved/disliked).

Доступные tools:
- get_interactions_summary() — общие счётчики + топ-темы по лайкам.
- get_user_profile() — профиль и skill_profile.

Правила:
1. Сначала ответь на конкретный вопрос (например, «что я лайкал?»).
2. Если уместно — добавь 1-2 инсайта («ты много лайкал X, а Y почти не
   трогал», «твой топик-вес ai_ml сильно вырос»).
3. Цифры — короткие и читаемые.
4. Стиль: дружелюбный, конкретный. Telegram-friendly.
5. Никаких RECOMMENDED_IDS — этот специалист не рекомендует.
"""


def summary_specialist_node(state: CopilotState) -> dict:
    tool_log = list(state.get("tool_calls_log") or [])

    user_msg = (
        f"Запрос: {state.get('goal', '')}\n\n"
        f"Профиль:\n{json.dumps(state.get('user_profile', {}), ensure_ascii=False)}\n\n"
        f"История (срез):\n{json.dumps(state.get('interaction_context', {}), ensure_ascii=False)}\n\n"
        f"Предыдущие turn'ы:\n{format_history(state.get('history'))}"
    )

    answer = invoke_with_tools(
        system_prompt=_SYSTEM,
        user_prompt=user_msg,
        db=state["db"],
        telegram_id=state["telegram_id"],
        tool_names=["get_interactions_summary", "get_user_profile"],
        tool_log=tool_log,
    )

    return {
        "answer": answer,
        "recommended_event_ids": [],
        "tool_calls_log": tool_log,
        "specialist": SPECIALIST_NAME,
    }
