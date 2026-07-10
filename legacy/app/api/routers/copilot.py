"""Copilot router.

Endpoints:
- POST /copilot/{telegram_id}              one-shot (legacy compat)
- POST /copilot/{telegram_id}/turn         multi-turn (создаст сессию при необходимости)
- GET  /copilot/{telegram_id}/sessions     список открытых сессий пользователя
- POST /copilot/sessions/{session_id}/close
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.services.recommendation_service import get_recommendations_for_user
from app.core.utils import utcnow_naive as _utcnow
from app.db.dependencies import get_db
from app.db.models.copilot_session import CopilotSession
from app.db.models.event import Event
from app.db.models.user import User
from app.recommender.scoring import _get_event_topic_codes

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/copilot", tags=["copilot"])

_DEFAULT_K = 10
_MAX_HISTORY = 10  # храним в state последние N сообщений; средние — через compaction


def _compact_history(history: list[dict], *, keep_head: int, keep_tail: int) -> list[dict]:
    """Сжать длинную историю диалога: голова + LLM-summary середины + хвост.

    Раньше при превышении лимита тупо отрезали голову — терялись цель и
    ранние установки. Здесь голову сохраняем, середину сжимаем одной
    `system`-ноткой через LLM. При сбое LLM (rate-limit, circuit open) —
    деградируем в исходный sliding window, чтобы не блокировать ответ.
    """
    if len(history) <= keep_head + keep_tail:
        return history

    head = history[:keep_head]
    middle = history[keep_head:-keep_tail] if keep_tail > 0 else history[keep_head:]
    tail = history[-keep_tail:] if keep_tail > 0 else []

    if not middle:
        return head + tail

    # Формируем текст для суммаризации.
    lines: list[str] = []
    for msg in middle:
        role = msg.get("role", "?")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{role}] {content[:400]}")
    if not lines:
        return head + tail

    summary_text: str | None = None
    try:
        from app.agents.recommendation.llm import llm
        sys_prompt = (
            "Ты сжимаешь середину диалога между пользователем и AI-помощником "
            "EventMind в КРАТКУЮ выжимку (3-6 предложений). Сохрани:\n"
            "1) цели пользователя и его текущий контекст;\n"
            "2) ключевые факты, на которые помощник уже опирался;\n"
            "3) принятые решения и предпочтения.\n"
            "Не выдумывай. Не цитируй дословно — пересказывай."
        )
        user_prompt = "Сжать в выжимку:\n\n" + "\n".join(lines)
        resp = llm.invoke([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ])
        summary_text = (getattr(resp, "content", None) or "").strip() or None
    except Exception as e:
        logger.warning("copilot history compaction failed, falling back to slice: %s", e)
        summary_text = None

    if summary_text is None:
        return head + tail

    summary_msg = {
        "role": "system",
        "content": f"[Сводка предыдущих {len(middle)} сообщений диалога]\n{summary_text}",
        "ts": _utcnow().isoformat(),
    }
    return head + [summary_msg] + tail


class CopilotRequest(BaseModel):
    goal: str


class CopilotTurnRequest(BaseModel):
    message: str
    session_id: int | None = None


def _load_history(db: Session, session_id: int) -> tuple[CopilotSession, list[dict]]:
    sess = db.query(CopilotSession).filter(CopilotSession.id == session_id).first()
    if sess is None:
        raise ValueError("session not found")
    try:
        history = json.loads(sess.messages_json or "[]")
    except Exception:
        history = []
    return sess, history


def _save_history(db: Session, sess: CopilotSession, history: list[dict]) -> None:
    sess.messages_json = json.dumps(history, ensure_ascii=False)
    sess.last_message_at = _utcnow()
    db.flush()
    db.commit()


def _enrich_cards(db: Session, recommended_ids: list[int]) -> list[dict]:
    if not recommended_ids:
        return []
    events_by_id = {
        e.id: e for e in db.query(Event).filter(Event.id.in_(recommended_ids)).all()
    }
    return [
        {
            "event_id": eid,
            "title": events_by_id[eid].title,
            "format": events_by_id[eid].format,
            "city": events_by_id[eid].city,
            "date": events_by_id[eid].date,
            "topics": list(_get_event_topic_codes(events_by_id[eid])),
            "source_url": events_by_id[eid].source_url,
        }
        for eid in recommended_ids
        if eid in events_by_id
    ]


def _invoke_graph(
    *, db: Session, user: User, telegram_id: int, goal: str,
    history: list[dict], k: int, limit: int,
) -> dict:
    from app.agents.copilot.agent import copilot_graph
    result = copilot_graph.invoke({
        "goal": goal,
        "telegram_id": telegram_id,
        "db": db,
        "k": k,
        "limit": limit,
        "history": history,
        "answer": "",
        "recommended_event_ids": [],
    })
    return result


@router.post("/{telegram_id}")
def copilot(
    telegram_id: int,
    payload: CopilotRequest,
    limit: int = Query(default=3, ge=1, le=10),
    k: int = Query(default=_DEFAULT_K, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """One-shot Copilot (без сохранения сессии). Сохранён ради обратной совместимости."""
    from app.core.prompt_safety import (
        DEFAULT_COPILOT_MAX_CHARS,
        has_injection_hints,
        sanitize_user_text,
    )

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "Профиль не найден. Сначала настрой профиль через /start."}

    safe_goal = sanitize_user_text(payload.goal, max_chars=DEFAULT_COPILOT_MAX_CHARS)
    if has_injection_hints(safe_goal):
        logger.info(
            "Copilot one-shot: goal contains injection hints (telegram_id=%s)", telegram_id,
        )
    try:
        result = _invoke_graph(
            db=db, user=user, telegram_id=telegram_id,
            goal=safe_goal, history=[], k=k, limit=limit,
        )
        ids = result.get("recommended_event_ids", [])[:limit]
        return {
            "success": True,
            "answer": result.get("answer", ""),
            "cards": _enrich_cards(db, ids),
            "retrieved_ids": [e["id"] for e in result.get("events", [])],
            "tool_calls": result.get("tool_calls_log", []),
            "specialist": result.get("specialist"),
            "intent": result.get("intent"),
            "routing_reason": result.get("routing_reason"),
        }
    except Exception:
        logger.exception("Copilot one-shot failed (telegram_id=%s)", telegram_id)
        try:
            recs = get_recommendations_for_user(db, telegram_id)[:limit]
            return {
                "success": True,
                "answer": "Подобрал события по твоему профилю (AI-помощник временно недоступен).",
                "cards": recs,
            }
        except Exception:
            logger.exception("Copilot fallback also failed (telegram_id=%s)", telegram_id)
            return {"success": False, "message": "Copilot временно недоступен."}


@router.post("/{telegram_id}/turn")
def copilot_turn(
    telegram_id: int,
    payload: CopilotTurnRequest,
    limit: int = Query(default=3, ge=1, le=10),
    k: int = Query(default=_DEFAULT_K, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Multi-turn copilot. Если session_id не передан — создаёт новую сессию."""
    from app.core.prompt_safety import (
        DEFAULT_COPILOT_MAX_CHARS,
        has_injection_hints,
        sanitize_user_text,
    )

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "Профиль не найден."}

    # Sanitize user-message ДО того как класть в history (БД) и в LLM-промпт.
    safe_message = sanitize_user_text(payload.message, max_chars=DEFAULT_COPILOT_MAX_CHARS)
    if has_injection_hints(safe_message):
        logger.info(
            "Copilot turn: message contains injection hints (telegram_id=%s)", telegram_id,
        )

    # Получаем или создаём сессию
    if payload.session_id is not None:
        try:
            sess, history = _load_history(db, payload.session_id)
            if sess.user_id != user.id:
                return {"success": False, "message": "Сессия принадлежит другому пользователю."}
        except ValueError:
            return {"success": False, "message": "Сессия не найдена."}
    else:
        sess = CopilotSession(user_id=user.id, messages_json="[]")
        db.add(sess)
        db.flush()
        history = []

    # User-message → history (уже sanitized)
    history.append({"role": "user", "content": safe_message, "ts": _utcnow().isoformat()})
    # Цель из последнего user-message (для retrieve)
    goal = safe_message

    try:
        result = _invoke_graph(
            db=db, user=user, telegram_id=telegram_id,
            goal=goal, history=history, k=k, limit=limit,
        )
        ids = result.get("recommended_event_ids", [])[:limit]
        answer = result.get("answer", "")

        # Assistant-message → history
        history.append({
            "role": "assistant",
            "content": answer,
            "recommended_ids": ids,
            "ts": _utcnow().isoformat(),
        })
        # Compaction: вместо тупого среза сжимаем средние сообщения
        # 1-2 LLM-summary turn'ами. Первые 2 и последние _MAX_HISTORY*2 - 2
        # сохраняются как есть — голова диалога часто содержит цель/роль,
        # а хвост важен для текущего turn'а.
        if len(history) > _MAX_HISTORY * 2:
            history = _compact_history(history, keep_head=2, keep_tail=_MAX_HISTORY * 2 - 2)
        _save_history(db, sess, history)

        # Long-term memory: best-effort extract из этого turn'а
        try:
            from app.core.config import settings as _settings
            if getattr(_settings, "memory_enabled", True):
                from app.recommender.memory import extract_from_dialog
                extract_from_dialog(
                    db, user, history[-2:],  # последняя пара user/assistant
                    source=f"dialog:session:{sess.id}",
                )
                db.commit()
        except Exception:
            pass

        return {
            "success": True,
            "session_id": sess.id,
            "answer": answer,
            "cards": _enrich_cards(db, ids),
            "retrieved_ids": [e["id"] for e in result.get("events", [])],
            "tool_calls": result.get("tool_calls_log", []),
            "specialist": result.get("specialist"),
            "intent": result.get("intent"),
            "routing_reason": result.get("routing_reason"),
            "turns": len([m for m in history if m["role"] == "user"]),
        }
    except Exception as e:
        logger.exception(
            "Copilot turn failed (telegram_id=%s, session_id=%s): %s",
            telegram_id, sess.id, e,
        )
        history.append({"role": "assistant", "content": f"(ошибка: {e})", "ts": _utcnow().isoformat()})
        _save_history(db, sess, history)
        return {"success": False, "session_id": sess.id, "message": "Copilot временно недоступен."}


@router.get("/{telegram_id}/sessions")
def list_sessions(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "sessions": []}
    rows = (
        db.query(CopilotSession)
        .filter(CopilotSession.user_id == user.id, CopilotSession.closed == 0)
        .order_by(CopilotSession.last_message_at.desc())
        .limit(20)
        .all()
    )
    return {
        "success": True,
        "sessions": [
            {
                "id": s.id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
                "turns": len([m for m in json.loads(s.messages_json or "[]") if m.get("role") == "user"]),
            }
            for s in rows
        ],
    }


@router.post("/sessions/{session_id}/close")
def close_session(session_id: int, db: Session = Depends(get_db)):
    sess = db.query(CopilotSession).filter(CopilotSession.id == session_id).first()
    if not sess:
        return {"success": False, "message": "Сессия не найдена."}
    sess.closed = 1
    db.commit()
    return {"success": True}
