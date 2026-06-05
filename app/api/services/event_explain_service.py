"""Человеческое описание события — для кнопки «📖 Подробнее» в боте.

Отличие от `get_why_explanation_for_user`: тут нет персонализации, нет скоров,
нет упоминания алгоритма. Просто живой пересказ: что за событие, для кого,
о чём, на что обратить внимание. Понятно любому пользователю.

Кэш — in-memory с TTL: одно и то же событие может разглядывать много людей
за день, повторно жечь LLM-токены на тот же контент бессмысленно. При
рестарте процесса кэш сбрасывается — это нормально, LLM-вызов недорогой.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from threading import Lock

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.utils import utcnow_naive
from app.db.models.event import Event

logger = logging.getLogger(__name__)

# event_id -> (summary, expires_at). Защита Lock'ом — несколько FastAPI
# воркеров в одном процессе будут лезть параллельно.
_CACHE: dict[int, tuple[str, datetime]] = {}
_CACHE_LOCK = Lock()
_TTL = timedelta(hours=6)


def _cached(event_id: int) -> str | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(event_id)
        if not entry:
            return None
        summary, expires_at = entry
        if utcnow_naive() >= expires_at:
            _CACHE.pop(event_id, None)
            return None
        return summary


def _store(event_id: int, summary: str) -> None:
    with _CACHE_LOCK:
        _CACHE[event_id] = (summary, utcnow_naive() + _TTL)


def invalidate(event_id: int | None = None) -> None:
    """Сбросить кэш — целиком или для одного события."""
    with _CACHE_LOCK:
        if event_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(event_id, None)


def _fallback_summary(event: Event) -> str:
    """Если LLM недоступна — собираем краткое описание из полей события.

    Текст всё ещё «человеческий»: без скоров, без алгоритмических деталей.
    """
    parts: list[str] = []
    parts.append(event.title or "Событие")

    facts: list[str] = []
    if event.event_type:
        facts.append(f"тип: {event.event_type}")
    if event.format and event.format != "unknown":
        facts.append(f"формат: {event.format}")
    if event.city and event.city not in ("unknown", "any"):
        facts.append(f"город: {event.city}")
    if event.level and event.level not in ("unknown", "any"):
        facts.append(f"уровень: {event.level}")
    if facts:
        parts.append(" · ".join(facts))

    if (event.description or "").strip():
        parts.append((event.description or "").strip()[:600])

    return "\n\n".join(parts)


def _build_summary_via_llm(event: Event) -> str | None:
    """Один LLM-вызов: 4–6 предложений на русском, простым языком."""
    try:
        from app.agents.recommendation.llm import llm

        sys_prompt = (
            "Ты — помощник EventMind. Тебе передают карточку IT-мероприятия. "
            "Твоя задача — пересказать её обычному человеку: что это за "
            "событие, для кого, о чём пойдёт речь, на что обратить внимание. "
            "Пиши на русском, дружелюбно и просто.\n\n"
            "ПРАВИЛА:\n"
            "1) 4–6 предложений, без подзаголовков и буллетов.\n"
            "2) Опирайся ТОЛЬКО на переданные данные. Не выдумывай спикеров, "
            "темы докладов, число участников, формат — если их нет в карточке.\n"
            "3) НЕ упоминай: алгоритм, скоры, рейтинг, рекомендательную "
            "систему, embedding, cosine, bayesian, «вам подходит», «именно "
            "для вас». Это просто описание события, а не объяснение «почему "
            "вам».\n"
            "4) ЗАПРЕЩЕНЫ маркетинговые штампы: «уникальная возможность», "
            "«не пропустите», «обязательно посетите», «расширьте кругозор».\n"
            "5) Если в описании указаны конкретные технологии — назови их "
            "своими словами.\n"
            "6) Если данных мало (только заголовок и пара слов) — честно "
            "напиши «по карточке известно немного: …» и не растягивай искусственно."
        )

        tech: list[str] = []
        try:
            if event.tech_stack:
                raw = json.loads(event.tech_stack) if isinstance(event.tech_stack, str) else []
                tech = raw if isinstance(raw, list) else []
        except Exception:
            tech = []

        ev_lines = [f"Название: {event.title}"]
        if event.event_type:
            ev_lines.append(f"Тип события: {event.event_type}")
        if event.format and event.format != "unknown":
            ev_lines.append(f"Формат: {event.format}")
        if event.city and event.city not in ("unknown", "any"):
            ev_lines.append(f"Город: {event.city}")
        if event.level and event.level not in ("unknown", "any"):
            ev_lines.append(f"Уровень: {event.level}")
        if event.seniority and event.seniority != "any":
            ev_lines.append(f"Целевой опыт аудитории: {event.seniority}")
        if event.date:
            ev_lines.append(f"Дата (как указано в источнике): {event.date}")
        if tech:
            ev_lines.append(f"Технологии: {', '.join(tech[:10])}")
        if (event.description or "").strip():
            ev_lines.append(f"Описание из источника: {(event.description or '')[:1200]}")

        user_prompt = "КАРТОЧКА СОБЫТИЯ:\n" + "\n".join(ev_lines)

        result = llm.invoke(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": user_prompt}]
        )
        text = getattr(result, "content", None) or str(result)
        text = text.strip()
        return text or None
    except Exception as e:
        logger.warning("event-explain LLM failed for event_id=%s: %s", event.id, e)
        return None


def explain_event(db: Session, event_id: int) -> dict:
    """Человеческое описание события для бота. Кэширует результат."""
    cached = _cached(event_id)
    if cached:
        return {"summary": cached, "cached": True}

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    summary = _build_summary_via_llm(event) or _fallback_summary(event)
    _store(event_id, summary)
    return {"summary": summary, "cached": False}
