"""AI-рекомендации (вариант C — hybrid + один LLM-вызов).

Старая 4-нодовая LangGraph-цепочка (user_profile → event_analyzer →
recommendation → explanation) убрана: она делала 4 LLM-вызова, отправляла
все 50 событий в каждый и жёстко возвращала ровно 3 карточки.

Сейчас:
  - кандидатов отбирает hybrid_score (детерминированно, миллисекунды),
  - один LLM-вызов пишет короткие объяснения для топ-N,
  - параметр `limit` (1..10) реально влияет на длину выдачи.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.services.ai_recommendation_service import build_ai_answer, build_ai_cards
from app.db.dependencies import get_db

router = APIRouter(prefix="/agent-recommendations", tags=["agent-recommendations"])


@router.get("/{telegram_id}")
def get_agent_recommendations(
    telegram_id: int,
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return build_ai_answer(db, telegram_id, limit=limit)


@router.get("/{telegram_id}/cards")
def get_agent_recommendation_cards(
    telegram_id: int,
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return build_ai_cards(db, telegram_id, limit=limit)
