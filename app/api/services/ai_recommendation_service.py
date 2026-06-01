"""Быстрая AI-выдача карточек рекомендаций (вариант C).

Старый граф (4 ноды LLM) был медленным и жёстко возвращал ровно 3 карточки.
Новая схема:

  1. hybrid_score даёт отранжированный top-N кандидатов (детерминированно, ~0.5 c).
  2. ОДИН LLM-вызов берёт top-N и пишет короткое объяснение для каждой
     карточки (1-2 предложения). Pydantic-валидация результата.
  3. Если LLM упал или вернул мусор — карточки отдаются с rule-based-
     объяснениями из get_recommendations_for_user (фолбэк без даунтайма).

Получается:
  - один LLM-вызов вместо четырёх (~2-3 c вместо ~12-18 c),
  - параметр `limit` действительно работает (1..10),
  - все поля карточки совпадают с обычной /recommendations — UI бота
    показывает 💡 Почему: из score_breakdown без дополнительной работы.
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.agents.recommendation.llm import llm
from app.api.services.recommendation_service import get_recommendations_for_user

logger = logging.getLogger(__name__)


class AIReason(BaseModel):
    event_id: int = Field(description="id события из переданного списка")
    reason: str = Field(description="1-2 предложения, почему подходит пользователю")


class AIReasonBatch(BaseModel):
    items: list[AIReason] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
Ты — AI-помощник в системе подбора IT-событий EventMind.
Тебе подаются: профиль пользователя и УЖЕ отобранные кандидаты-события (отбор
сделан гибридным рекомендером — твоя задача только написать объяснения).

Для каждого события напиши 1-2 коротких предложения на русском:
- почему конкретно ЭТОТ человек найдёт его полезным;
- ссылайся на его темы / формат / город / уровень, если они совпадают;
- не выдумывай факты, пользуйся только данными из карточки.

Верни СТРОГО валидный JSON-объект следующей формы:
{
  "items": [
    {"event_id": <id>, "reason": "..."},
    ...
  ]
}
Без преамбулы, без обрамления ```json. Все события из ввода ДОЛЖНЫ присутствовать
в items с тем же event_id.
"""


def _build_user_prompt(user_profile: dict, cards: list[dict]) -> str:
    short_cards = [
        {
            "event_id": c.get("event_id"),
            "title": c.get("title"),
            "topics": c.get("topics", []),
            "format": c.get("format"),
            "city": c.get("city"),
            "level": c.get("level"),
            "date": c.get("date"),
            "summary": (c.get("summary") or c.get("description") or "")[:300],
            "tech_stack": c.get("tech_stack") or [],
        }
        for c in cards
    ]
    return (
        f"Профиль пользователя:\n{json.dumps(user_profile, ensure_ascii=False)}\n\n"
        f"Кандидаты ({len(short_cards)} шт.):\n"
        f"{json.dumps(short_cards, ensure_ascii=False, indent=2)}\n\n"
        f"Напиши объяснения для всех {len(short_cards)} событий в указанном JSON-формате."
    )


def _parse_reasons(raw: str) -> dict[int, str]:
    """Достать {event_id: reason} из LLM-ответа.

    Сначала пытаемся честно распарсить через pydantic, на случай если LLM
    обернул в ```json или добавил преамбулу — вытаскиваем regex'ом первый
    {...}-блок.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return {item.event_id: item.reason for item in AIReasonBatch.model_validate_json(text).items}
    except ValidationError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return {item.event_id: item.reason for item in AIReasonBatch.model_validate_json(match.group()).items}
    except (ValidationError, ValueError) as e:
        logger.warning("AI reasons parse failed: %s; raw=%r", e, text[:200])
        return {}


def build_ai_cards(db: Session, telegram_id: int, limit: int = 5) -> dict:
    """Главная точка входа: отбор + AI-пояснения.

    Возвращает {"success": bool, "cards": [...], "message"?: str}.
    Карточки совместимы по полям с /recommendations — UI бота показывает
    их той же функцией format_event_card.
    """
    limit = max(1, min(int(limit or 5), 10))

    # 1. Hybrid-отбор. Бросит HTTPException, если пользователя нет —
    # дадим ему пробросить выше: endpoint вернёт честный 404.
    ranked = get_recommendations_for_user(db, telegram_id)
    if not ranked:
        return {"success": False, "message": "Нет событий для рекомендации.", "cards": []}

    top = ranked[:limit]

    # 2. Один LLM-вызов на пакет пояснений.
    user_profile = {
        "telegram_id": telegram_id,
        "topics_topN": _top_topics_from_signals(top[0].get("explanation_details", {})),
    }
    prompt_user = _build_user_prompt(user_profile, top)

    ai_reasons: dict[int, str] = {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt_user),
        ])
        ai_reasons = _parse_reasons(getattr(response, "content", "") or "")
    except Exception as e:
        logger.warning("AI explanation batch failed, using rule-based reasons: %s", e)

    # 3. Подменяем explanation на AI-вариант там, где он есть. Остальные поля
    # карточки уже корректны (включая score_breakdown — UI рендерит «💡 Почему»).
    cards = []
    for c in top:
        new_card = dict(c)
        reason = ai_reasons.get(c.get("event_id"))
        if reason:
            new_card["explanation"] = reason.strip()
        # Старое API возвращало score как "8/10" — оставим число для UI.
        new_card["score"] = c.get("score")
        cards.append(new_card)

    return {"success": True, "cards": cards}


def _top_topics_from_signals(details: dict) -> list[str]:
    """Достаём топ-темы из history_signals для краткого профиля в промпте."""
    if not isinstance(details, dict):
        return []
    sig = details.get("history_signals")
    if isinstance(sig, dict):
        topics = sig.get("top_liked_topics") or sig.get("top_topics") or []
        if isinstance(topics, list):
            return [str(t) for t in topics[:5]]
    return []


def build_ai_answer(db: Session, telegram_id: int, limit: int = 3) -> dict:
    """Legacy-совместимая обёртка для /agent-recommendations/{tid}.

    Возвращает не только карточки, но и финальный нарратив-ответ для
    подмены {success, answer} прежнего endpoint'а.
    """
    cards_result = build_ai_cards(db, telegram_id, limit=limit)
    if not cards_result.get("success"):
        return {"success": False, "message": cards_result.get("message", "AI-сервис недоступен.")}

    cards = cards_result.get("cards", [])
    if not cards:
        return {"success": True, "answer": "Пока нет подходящих событий."}

    lines = ["🎯 Я подобрал для тебя события:", ""]
    for i, c in enumerate(cards, 1):
        topics = ", ".join(c.get("topics", []))
        lines.append(f"{i}. <b>{c.get('title', '')}</b>")
        if topics:
            lines.append(f"   Темы: {topics}")
        lines.append(f"   Почему подходит: {c.get('explanation', '')}")
        lines.append(f"   Оценка: {c.get('score', '?')}")
        lines.append("")
    lines.append("Можешь поставить 👍 или 👎, чтобы я лучше понял твои интересы.")

    return {"success": True, "answer": "\n".join(lines), "cards": cards}
