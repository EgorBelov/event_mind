"""EventExplainerAgent — объяснить, почему конкретное событие подошло
пользователю (или почему не подошло).

В отличие от других специалистов, не ищет события — он работает с конкретным
target_event_id, который supervisor извлекает из запроса. Делает один вызов
explain_event tool и нарратизирует структурированное объяснение.

Tools: explain_event, get_user_profile.
"""
from __future__ import annotations

import json
import re

from app.agents.copilot.common import format_history, invoke_with_tools
from app.agents.copilot.state import CopilotState

SPECIALIST_NAME = "event_explainer"


_SYSTEM = """\
Ты — объяснитель рекомендаций в EventMind.

Тебе подаётся:
- запрос пользователя,
- target_event_id (если supervisor смог его извлечь) — конкретное событие
  для объяснения,
- история диалога.

Доступные tools:
- explain_event(event_id) — получить структурированное объяснение
  (topic_match, format_match, semantic_similarity, history_signals,
  bayesian_posterior, counterfactual, score_breakdown).
- get_user_profile() — если нужно сверить с целями пользователя.

Правила:
1. Если target_event_id задан — обязательно дёрни explain_event(target_event_id)
   и переведи структурированный вывод в человеческий объяснительный текст.
2. Если target_event_id не задан — попроси пользователя уточнить, какое
   событие имеется в виду (например, «по ID, как в карточке: #123»).
3. Не выдумывай причин, которых нет в результате explain_event.
4. Стиль: понятный, Telegram-friendly. Можно использовать буллеты.
5. RECOMMENDED_IDS не нужен — этот специалист не рекомендует новые события.
"""


_EVENT_ID_RE = re.compile(r"#\s*(\d+)|\bevent\s*#?\s*(\d+)|\bивент\s*#?\s*(\d+)", re.I)


def _fallback_extract_event_id(goal: str, state: CopilotState) -> int | None:
    """Если supervisor не выделил target_event_id, последняя попытка — regex."""
    if not goal:
        return None
    m = _EVENT_ID_RE.search(goal)
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                return int(g)
            except ValueError:
                pass
    return None


def event_explainer_node(state: CopilotState) -> dict:
    tool_log = list(state.get("tool_calls_log") or [])

    target = state.get("target_event_id") or _fallback_extract_event_id(state.get("goal", ""), state)

    user_msg = (
        f"Запрос: {state.get('goal', '')}\n"
        f"target_event_id: {target if target is not None else 'не определён'}\n\n"
        f"Профиль:\n{json.dumps(state.get('user_profile', {}), ensure_ascii=False)}\n\n"
        f"История диалога:\n{format_history(state.get('history'))}"
    )
    if target is None:
        user_msg += (
            "\n\nВНИМАНИЕ: ID события не определён. Попроси у пользователя уточнить, "
            "какое событие он имеет в виду (формат: #123)."
        )

    answer = invoke_with_tools(
        system_prompt=_SYSTEM,
        user_prompt=user_msg,
        db=state["db"],
        telegram_id=state["telegram_id"],
        tool_names=["explain_event", "get_user_profile"],
        tool_log=tool_log,
    )

    return {
        "answer": answer,
        "recommended_event_ids": [],
        "tool_calls_log": tool_log,
        "specialist": SPECIALIST_NAME,
    }
