"""Long-term memory agent (mem0-style).

Активная память: вместо того чтобы пассивно хранить лайки в `interactions`,
LLM сам решает, что значимо запомнить, и пишет заметки от первого лица
с категорией и salience-весом в таблицу `user_memories`.

Точки входа:
- `extract_from_interaction(db, user, event, action)` — после каждого
  лайка/дизлайка/сейва.
- `extract_from_dialog(db, user, messages)` — после каждого Copilot-turn'а.
- `write_memory(...)` — низкоуровневая запись.
- `recall(db, user, query, k)` — семантический top-k.
- `compact_user_memories(db, user)` — LLM-суммаризация при росте.

Все экстрактные вызовы best-effort: при сбое LLM/эмбеддинга — пропуск
без падения основного потока.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.user_memory import UserMemory


logger = logging.getLogger(__name__)


# Категории — закрытый список, чтобы LLM не плодил вариации.
Category = Literal["interest", "dislike", "goal", "constraint", "context", "event_pref", "other"]
_VALID_CATEGORIES = {"interest", "dislike", "goal", "constraint", "context", "event_pref", "other"}

DEFAULT_MIN_SALIENCE = 4.0      # фильтр шумных заметок
COMPACT_THRESHOLD = 50          # после стольких заметок — сжимаем
COMPACT_TARGET_PER_CATEGORY = 5 # сколько оставить в каждой категории


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─── Pydantic-схемы для LLM-извлечения ───────────────────────────────────


class MemoryItem(BaseModel):
    text: str = Field(description="Короткое утверждение о пользователе от третьего лица.")
    category: Category = Field(description="Одна из закрытых категорий.")
    salience: float = Field(ge=1.0, le=10.0, description="Насколько важно запомнить, 1..10.")


class MemoryExtractionResult(BaseModel):
    """LLM возвращает 0..N заметок. Пустой список = ничего значимого не нашлось."""
    items: list[MemoryItem] = Field(default_factory=list)


# ─── Низкоуровневые операции ──────────────────────────────────────────────


def write_memory(
    db: Session,
    user_id: int,
    text: str,
    *,
    category: str = "other",
    salience: float = 5.0,
    source: str | None = None,
) -> UserMemory | None:
    """Записать заметку с попыткой посчитать embedding. None при сбое."""
    text = (text or "").strip()
    if not text:
        return None
    if category not in _VALID_CATEGORIES:
        category = "other"
    salience = max(1.0, min(10.0, float(salience)))

    emb_json: str | None = None
    try:
        from app.recommender.embeddings import embed_text
        emb_json = json.dumps(embed_text(text))
    except Exception:
        emb_json = None

    row = UserMemory(
        user_id=user_id,
        text=text,
        category=category,
        salience=salience,
        source=source,
        embedding=emb_json,
    )
    db.add(row)
    db.flush()
    return row


def recall(
    db: Session,
    user_id: int,
    query: str,
    k: int = 5,
    *,
    min_salience: float = 0.0,
) -> list[dict[str, Any]]:
    """Семантический top-k recall с инкрементом access_count.

    Если embedding-модель недоступна или у заметок нет embedding'ов —
    fallback на сортировку по salience DESC + recency.
    """
    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id, UserMemory.salience >= min_salience)
        .all()
    )
    if not rows:
        return []

    ranked: list[tuple[float, UserMemory]] = []
    try:
        from app.recommender.embeddings import embed_text, cosine_similarity
        q_vec = embed_text(query)
        for row in rows:
            sim = 0.0
            if row.embedding:
                try:
                    sim = cosine_similarity(q_vec, json.loads(row.embedding))
                except Exception:
                    sim = 0.0
            # Скорер: cos * 0.7 + salience-norm * 0.3 (salience 1..10 → 0.1..1.0)
            score = sim * 0.7 + (row.salience / 10.0) * 0.3
            ranked.append((score, row))
    except Exception:
        # Fallback: salience + recency (по убывающему id — более новые выше)
        max_id = max(row.id for row in rows)
        ranked = [
            (
                (row.salience / 10.0) + (1.0 / (1.0 + max(0, max_id - row.id))),
                row,
            )
            for row in rows
        ]

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:k]

    now = _utcnow()
    out: list[dict[str, Any]] = []
    for score, row in top:
        row.access_count = (row.access_count or 0) + 1
        row.last_accessed_at = now
        out.append({
            "id": row.id,
            "text": row.text,
            "category": row.category,
            "salience": row.salience,
            "source": row.source,
            "score": round(float(score), 4),
            "access_count": row.access_count,
        })
    db.flush()
    return out


# ─── LLM-извлечение из feedback'а ─────────────────────────────────────────


_INTERACTION_SYSTEM = """\
Ты — long-term memory agent системы EventMind. Твоя задача: из одного
взаимодействия пользователя с событием извлечь 0..2 заметки о его
вкусах/целях/ограничениях, если в этом есть что-то значимое и НЕ
тривиальное.

Тривиальное (НЕ записывай):
- «пользователю интересна тема X» если она уже в его profile.topics.
- «лайкнул событие Y» — сам факт лайка уже хранится отдельно.

Значимое (записывай):
- Неожиданный паттерн: дизлайк топика, который у пользователя в интересах.
- Сильное предпочтение формата/города/уровня по контексту.
- Тема, которой нет в profile.topics, но видно интерес.

Категории:
- interest, dislike, goal, constraint, context, event_pref, other.

salience: 1 (мимолётное) … 10 (краеугольный факт).

Верни СТРОГО JSON:
{"items": [{"text": "...", "category": "interest", "salience": 7}, ...]}
Если ничего значимого — {"items": []}. Никакого текста вне JSON.
"""


def _parse_llm_json(content: str) -> dict | None:
    text = (content or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _llm_extract(system_prompt: str, user_msg: str) -> MemoryExtractionResult:
    """Общий extract-шаг. При сбое возвращает пустой результат."""
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from app.agents.recommendation.llm import llm
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_msg)])
        data = _parse_llm_json(response.content or "")
        if data is None:
            return MemoryExtractionResult(items=[])
        return MemoryExtractionResult.model_validate(data)
    except (ValidationError, Exception) as e:
        logger.debug("memory: LLM extract failed: %s", e)
        return MemoryExtractionResult(items=[])


def extract_from_interaction(
    db: Session,
    user: User,
    event: Event,
    action: str,
    *,
    min_salience: float = DEFAULT_MIN_SALIENCE,
) -> int:
    """LLM смотрит на feedback и пишет заметки, если есть что значимое.

    Возвращает число записанных заметок. Best-effort: при любом сбое 0.
    """
    if action not in {"like", "dislike", "save"}:
        return 0
    try:
        from app.recommender.scoring import _get_event_topic_codes, _get_user_topic_codes
        from app.recommender.user_model import parse_topic_weights

        user_topics = list(_get_user_topic_codes(user))
        event_topics = list(_get_event_topic_codes(event))
        topic_weights = parse_topic_weights(user.topic_weights)

        user_msg = (
            f"Действие: {action}\n"
            f"Событие #{event.id}: {event.title}\n"
            f"  description: {(event.description or '')[:300]}\n"
            f"  format: {event.format}, city: {event.city}, level: {event.level}\n"
            f"  topics: {event_topics}\n"
            f"Пользовательский профиль:\n"
            f"  topics: {user_topics}\n"
            f"  preferred_format: {user.preferred_format}, city: {user.city}\n"
            f"  topic_weights: {topic_weights}\n\n"
            "Извлеки 0..2 заметки в JSON-формате."
        )
        result = _llm_extract(_INTERACTION_SYSTEM, user_msg)
    except Exception:
        return 0

    written = 0
    for item in result.items:
        if item.salience < min_salience:
            continue
        write_memory(
            db, user.id, item.text,
            category=item.category, salience=item.salience,
            source=f"interaction:{action}:event:{event.id}",
        )
        written += 1
    if written:
        db.flush()
    return written


# ─── LLM-извлечение из диалога ────────────────────────────────────────────


_DIALOG_SYSTEM = """\
Ты — long-term memory agent. Из последних реплик Copilot-диалога извлеки
0..3 заметки о пользователе, если в диалоге всплыли НОВЫЕ факты:
явные цели, ограничения, предпочтения, контекст работы.

Не пиши тривиальные «пользователь спросил X» — нужны устойчивые факты
(«нужен план перехода в ML за 6 месяцев», «не может ездить в офлайн в МСК»).

Категории: interest, dislike, goal, constraint, context, event_pref, other.
salience: 1..10.

Верни строго: {"items": [{"text": "...", "category": "...", "salience": 7}, ...]}
"""


def extract_from_dialog(
    db: Session,
    user: User,
    messages: list[dict[str, Any]],
    *,
    window: int = 6,
    min_salience: float = DEFAULT_MIN_SALIENCE,
    source: str | None = None,
) -> int:
    """LLM смотрит на последние сообщения диалога и пишет факты."""
    if not messages:
        return 0
    snippet = []
    for m in messages[-window:]:
        role = m.get("role", "?")
        content = (m.get("content") or "")[:600]
        snippet.append(f"[{role}] {content}")
    user_msg = "Последние реплики:\n" + "\n".join(snippet) + "\n\nИзвлеки 0..3 заметки JSON."

    try:
        result = _llm_extract(_DIALOG_SYSTEM, user_msg)
    except Exception:
        return 0

    written = 0
    for item in result.items:
        if item.salience < min_salience:
            continue
        write_memory(
            db, user.id, item.text,
            category=item.category, salience=item.salience,
            source=source or "dialog",
        )
        written += 1
    if written:
        db.flush()
    return written


# ─── Compaction ───────────────────────────────────────────────────────────


_COMPACT_SYSTEM = """\
Ты — компактор памяти. Тебе подают набор заметок одной категории. Твоя
задача — слить пересекающиеся, выбросить устаревшие/слабые, и оставить
не более N самых полезных утверждений. Сохрани смысл, повысь salience
для повторяющихся фактов.

Верни строго:
{"items": [{"text": "...", "category": "<та же>", "salience": <число>}, ...]}
"""


def compact_user_memories(
    db: Session,
    user_id: int,
    *,
    threshold: int = COMPACT_THRESHOLD,
    target_per_category: int = COMPACT_TARGET_PER_CATEGORY,
) -> dict[str, Any]:
    """Сжать заметки пользователя через LLM, если их больше `threshold`."""
    total = db.query(UserMemory).filter(UserMemory.user_id == user_id).count()
    if total < threshold:
        return {"status": "skipped", "reason": "below_threshold", "total": total}

    by_cat: dict[str, list[UserMemory]] = {}
    for row in db.query(UserMemory).filter(UserMemory.user_id == user_id).all():
        by_cat.setdefault(row.category or "other", []).append(row)

    removed = 0
    added = 0
    for cat, rows in by_cat.items():
        if len(rows) <= target_per_category:
            continue
        notes = [
            {"text": r.text, "salience": r.salience, "access_count": r.access_count or 0}
            for r in rows
        ]
        user_msg = (
            f"Категория: {cat}\nЦель: оставить не более {target_per_category} заметок.\n\n"
            f"Заметки:\n{json.dumps(notes, ensure_ascii=False)}\n\n"
            "Верни JSON-объект {\"items\": [...]}."
        )
        result = _llm_extract(_COMPACT_SYSTEM, user_msg)
        if not result.items:
            continue
        for row in rows:
            db.delete(row)
            removed += 1
        for item in result.items[:target_per_category]:
            write_memory(
                db, user_id, item.text,
                category=cat, salience=item.salience,
                source="compaction",
            )
            added += 1

    db.flush()
    return {"status": "ok", "before": total, "removed": removed, "added": added}
