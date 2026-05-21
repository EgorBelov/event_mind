"""Supervisor-агент: классифицирует запрос пользователя в один из intent'ов
и роутит к нужному специалисту через LangGraph conditional edges.

Использует структурированный LLM-вывод через pydantic для надёжности
(JSON-mode + валидация + fallback на keyword-классификатор при сбое).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from app.agents.copilot.state import CopilotState


logger = logging.getLogger(__name__)


class SupervisorDecision(BaseModel):
    """Решение supervisor'а о маршрутизации запроса к специалисту."""
    intent: Literal["recommend", "career", "roadmap", "explain", "summary"] = Field(
        description=(
            "recommend: пользователь ищет события под текущий запрос;\n"
            "career: вопросы про карьеру, навыки, target_role, что учить;\n"
            "roadmap: запрос на план обучения с временными рамками;\n"
            "explain: 'почему ты рекомендовал X' или 'расскажи про event #N';\n"
            "summary: 'что я лайкал', 'мой профиль', 'история взаимодействий'."
        )
    )
    reasoning: str = Field(description="Одной фразой — почему именно этот intent.")
    target_event_id: Optional[int] = Field(
        default=None,
        description="Если intent=explain и упомянут конкретный event_id — указать его.",
    )
    horizon_months: Optional[int] = Field(
        default=None,
        description="Если intent=roadmap и упомянут срок — число месяцев.",
    )


_SUPERVISOR_SYSTEM = """\
Ты — supervisor мультиагентной системы EventMind. Твоя единственная задача:
классифицировать запрос пользователя в ОДИН из intent'ов и выделить служебные
параметры. Не отвечай по существу запроса — это сделает специалист.

Intents (выбери ровно один):
- recommend — найти подходящие IT-события под текущий запрос («посоветуй»,
  «найди», «что есть по теме X», «дай ивенты»).
- career — карьерный вопрос: «как стать», «что учить», «какие скиллы»,
  «какой target_role подходит», «оцени мою траекторию».
- roadmap — план обучения с временными рамками: «составь план на 3 месяца»,
  «обучающий маршрут до сениора», «sequence ивентов».
- explain — объяснить рекомендацию или конкретное событие: «почему ты
  предложил X», «расскажи про event #123», «что не так с #45».
- summary — анализ истории/профиля: «что я лайкал», «мой профиль», «топ-темы
  по моим лайкам», «история взаимодействий».

Верни СТРОГО JSON по схеме:
{
  "intent": "recommend",
  "reasoning": "...",
  "target_event_id": null,   // или число для intent=explain
  "horizon_months": null     // или число для intent=roadmap
}
Никакого текста вне JSON.
"""


def _llm_classify(goal: str, history_str: str) -> SupervisorDecision | None:
    """Структурированный LLM-вызов с pydantic-валидацией. None при сбое.

    Используем прямые SystemMessage/HumanMessage, а не ChatPromptTemplate,
    потому что в system-prompt есть JSON-пример с `{...}`, который
    шаблонизатор интерпретировал бы как переменные.
    """
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from app.agents.recommendation.llm import llm
        user_msg = f"Текущий запрос:\n{goal}\n\nИстория диалога:\n{history_str}\n\nВерни JSON-решение."
        response = llm.invoke([SystemMessage(content=_SUPERVISOR_SYSTEM), HumanMessage(content=user_msg)])
        text = (response.content or "").strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
        return SupervisorDecision.model_validate(data)
    except (ValidationError, json.JSONDecodeError, Exception) as e:
        logger.warning("supervisor: LLM classify failed: %s", e)
        return None


# Keyword-эвристики для fallback'а на случай недоступности LLM. Намеренно
# консервативные — если ни одна не сработала, дефолт = recommend.
_KEYWORD_PATTERNS: dict[str, list[str]] = {
    "explain": ["почему ты", "почему рекомендовал", "почему предложил", "расскажи про event",
                "расскажи про ивент", "что не так с", "explain"],
    "summary": ["что я лайкал", "мой профиль", "история взаимодейств", "мои лайки",
                "что у меня", "мои сохран"],
    "roadmap": ["план на ", "roadmap", "маршрут", "за 3 месяца", "за полгода", "за год",
                "sequence", "последовательност"],
    "career": ["target_role", "стать ml", "стать backend", "что учить", "какие скиллы",
                "карьер", "перейти в", "сменить роль", "junior", "middle", "senior"],
}


def _keyword_classify(goal: str) -> SupervisorDecision:
    text = (goal or "").lower()
    for intent, patterns in _KEYWORD_PATTERNS.items():
        if any(p in text for p in patterns):
            target = None
            horizon = None
            if intent == "explain":
                m = re.search(r"(?:event|ивент)\s*#?\s*(\d+)", text)
                if m:
                    target = int(m.group(1))
            if intent == "roadmap":
                m = re.search(r"(\d+)\s*(?:месяц|month)", text)
                if m:
                    horizon = int(m.group(1))
            return SupervisorDecision(
                intent=intent,  # type: ignore[arg-type]
                reasoning=f"keyword-fallback: matched '{intent}' patterns",
                target_event_id=target,
                horizon_months=horizon,
            )
    return SupervisorDecision(
        intent="recommend",
        reasoning="default: no specific intent detected",
    )


def supervisor_node(state: CopilotState) -> dict:
    """LangGraph-нода: классифицирует и пишет intent + параметры в state."""
    from app.agents.copilot.common import format_history

    goal = state.get("goal", "")
    history_str = format_history(state.get("history"))

    decision = _llm_classify(goal, history_str) or _keyword_classify(goal)

    return {
        "intent": decision.intent,
        "routing_reason": decision.reasoning,
        "target_event_id": decision.target_event_id,
        "horizon_months": decision.horizon_months,
    }


def route_after_supervisor(state: CopilotState) -> str:
    """LangGraph-router: имя следующей ноды по intent. Совпадает с именами
    специалистов в main графе.
    """
    intent = state.get("intent", "recommend")
    return {
        "recommend": "recommendation_specialist",
        "career": "career_coach",
        "roadmap": "roadmap_planner",
        "explain": "event_explainer",
        "summary": "summary_specialist",
    }.get(intent, "recommendation_specialist")
