import contextlib
import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.bayesian import update_stats_from_feedback
from app.recommender.explain import explain_event_detailed
from app.recommender.scoring import _get_event_topic_codes, score_event_for_user
from app.recommender.user_model import (
    apply_feedback_to_weights,
    dump_topic_weights,
    parse_topic_weights,
)

logger = logging.getLogger(__name__)

try:
    from app.recommender.hybrid import compute_score_breakdown as _compute_breakdown
    _HAS_HYBRID = True
except Exception:
    _HAS_HYBRID = False
    _compute_breakdown = None  # type: ignore


def refresh_user_embedding(db: Session, user: User) -> None:
    """Посчитать и закэшировать персональный embedding пользователя (best-effort).

    КРИТИЧНО: при сбое flush'а (SQLite locked, concurrent writer) обязательно
    rollback'аем сессию. Иначе она остаётся в "rollback required" state и
    любое следующее обращение к user.id/user.* пробрасывает PendingRollbackError —
    в результате весь GET /recommendations отваливался 500-кой, а бот показывал
    «Пока нет рекомендаций» при настроенном профиле.
    """
    try:
        from app.recommender.embeddings import build_rich_user_embedding
        interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
        emb = build_rich_user_embedding(user, interactions)
        user.embedding = json.dumps(emb)
        db.commit()
    except Exception as e:
        logger.warning("refresh_user_embedding failed, rollback: %s", e)
        with contextlib.suppress(Exception):
            db.rollback()


def get_recommendations_for_user(
    db: Session, telegram_id: int, limit: int = 25
) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Один раз на запрос: закэшировать вектор пользователя (user.embedding).
    refresh_user_embedding(db, user)

    # Precompute user embedding с session-blend — ОДИН раз на запрос
    # (а не на каждое из N событий). Нужен и для cosine-компонента, и для
    # кандидатного отбора через pgvector ниже.
    precomputed_user_emb = None
    try:
        from app.recommender.embeddings import (
            blend_user_embedding,
            build_session_embedding,
            get_or_build_user_embedding,
        )
        precomputed_user_emb = get_or_build_user_embedding(user)
        session_emb = build_session_embedding(db, user, window=5)
        if session_emb is not None:
            precomputed_user_emb = blend_user_embedding(
                precomputed_user_emb, session_emb, session_weight=0.3,
            )
    except Exception:
        precomputed_user_emb = None

    # Кандидатный отбор: на PostgreSQL+pgvector берём top-N по вектору через
    # индекс <=> (а не скорим весь каталог). На SQLite/без pgvector
    # pgvector_top_k_events вернёт [] → берём все события. joinedload по
    # event_topics убирает N+1 (иначе _get_event_topic_codes делает SELECT
    # на каждое событие — особенно дорого на PG по сети).
    from sqlalchemy.orm import joinedload

    candidate_pool = 300
    candidate_ids: list[int] = []
    if precomputed_user_emb is not None:
        try:
            from app.recommender.embeddings import pgvector_top_k_events
            candidate_ids = pgvector_top_k_events(db, precomputed_user_emb, k=candidate_pool)
        except Exception as e:
            logger.warning("pgvector candidate fetch failed: %s", e)
            candidate_ids = []

    base_q = db.query(Event).options(joinedload(Event.event_topics))
    events = (
        base_q.filter(Event.id.in_(candidate_ids)).all()
        if candidate_ids else base_q.all()
    )

    # Досчитать батчем недостающие векторы событий с записью в БД, чтобы
    # cosine-компонент не пересчитывал их лениво по одному.
    try:
        from app.recommender.embeddings import ensure_event_embeddings
        ensure_event_embeddings(db, events)
    except Exception:
        pass

    # Bayesian-параметры пользователя — грузим один раз на запрос.
    bayesian_stats = None
    try:
        from app.recommender.bayesian import load_user_stats
        bayesian_stats = load_user_stats(db, user.id)
    except Exception:
        bayesian_stats = None

    # Skill-профиль, если есть — переиспользуется в breakdown.
    try:
        from app.recommender.skill_gap import load_skill_profile
        skill_profile = load_skill_profile(db, user.id)
    except Exception:
        skill_profile = None

    # LinUCB-state — один раз на запрос (вместо N SELECT'ов из user_bandit_states).
    bandit_state = None
    if settings.bandit_enabled:
        try:
            from app.recommender.bandit import load_user_bandit
            bandit_state = load_user_bandit(db, user.id)
        except Exception as e:
            logger.warning("LinUCB state load failed for user %s: %s", user.id, e)
            bandit_state = None

    # Фаза 1 — ДЕШЁВЫЙ скоринг всех событий (без объяснений).
    # Раньше тяжёлый explain_event_detailed вызывался для КАЖДОГО события,
    # хотя в выдачу попадают единицы — отсюда «~16 c на список». Теперь
    # объяснения строятся только для возвращаемого top-N (фаза 3).
    scored = []
    for event in events:
        try:
            if _HAS_HYBRID and _compute_breakdown is not None:
                breakdown = _compute_breakdown(
                    user, event, db=db, bayesian_stats=bayesian_stats,
                    user_skill_profile=skill_profile,
                    precomputed_user_emb=precomputed_user_emb,
                    bandit_state=bandit_state,
                )
                score = float(sum(breakdown.values()))
            else:
                breakdown = {}
                score = float(score_event_for_user(user, event))
        except Exception:
            breakdown = {}
            score = float(score_event_for_user(user, event))

        scored.append({
            "_event": event,            # ссылка на ORM-объект для фазы 3
            "_breakdown_raw": breakdown,  # полная точность для объяснения
            "event_id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": list(_get_event_topic_codes(event)),
            "summary": getattr(event, "summary", None),
            "source_url": event.source_url,
            "target_audience": getattr(event, "target_audience", None),
            "tech_stack": _parse_json_field(getattr(event, "tech_stack", None)),
            "seniority": getattr(event, "seniority", None),
            "quality_score": getattr(event, "quality_score", None),
            "hype_score": getattr(event, "hype_score", None),
            "score": round(score, 2),
            "score_breakdown": {k: round(v, 3) for k, v in breakdown.items()},
        })

    # Фаза 2 — сортировка + MMR-диверсификация, затем срез до limit.
    scored.sort(key=lambda x: x["score"], reverse=True)
    if settings.mmr_enabled and len(scored) > 1:
        try:
            from app.recommender.diversity import mmr_rerank
            scored = mmr_rerank(scored, db, lambda_=settings.mmr_lambda)
        except Exception as e:
            logger.warning("MMR rerank failed: %s", e)
    if limit and limit > 0:
        scored = scored[:limit]

    # Фаза 3 — тяжёлое объяснение ТОЛЬКО для отобранных событий.
    results = []
    for item in scored:
        event = item.pop("_event")
        breakdown_raw = item.pop("_breakdown_raw")
        explanation = explain_event_detailed(
            user, event, db=db,
            precomputed_breakdown=breakdown_raw or None,
        )
        item["explanation"] = explanation["text"]
        item["explanation_details"] = {
            "topic_match": explanation["topic_match"],
            "format_match": explanation["format_match"],
            "city_match": explanation["city_match"],
            "semantic_similarity": explanation.get("semantic_similarity"),
            "history_signals": explanation["history_signals"],
        }
        results.append(item)

    return results


def _parse_json_field(value) -> list:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def create_interaction(db: Session, telegram_id: int, event_id: int, action: str) -> dict:
    if action not in {"like", "dislike", "save"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    current_weights = parse_topic_weights(user.topic_weights)
    event_topics = _get_event_topic_codes(event)

    if action in {"like", "dislike"}:
        opposite_action = "dislike" if action == "like" else "like"

        existing_same = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == action)
            .first()
        )
        if existing_same:
            db.delete(existing_same)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(current_weights, event_topics, action, direction=-1)
            )
            _safe_bayes_update(db, user.id, event_topics, action, direction=-1)
            _safe_bandit_update(db, user, event, action, direction=-1)
            db.commit()
            return {"success": True, "message": f"Interaction '{action}' removed", "topic_weights": parse_topic_weights(user.topic_weights)}

        existing_opposite = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == opposite_action)
            .first()
        )
        if existing_opposite:
            db.delete(existing_opposite)
            current_weights = apply_feedback_to_weights(current_weights, event_topics, opposite_action, direction=-1)
            _safe_bayes_update(db, user.id, event_topics, opposite_action, direction=-1)
            _safe_bandit_update(db, user, event, opposite_action, direction=-1)

    elif action == "save":
        existing_save = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.event_id == event_id, Interaction.action == "save")
            .first()
        )
        if existing_save:
            db.delete(existing_save)
            user.topic_weights = dump_topic_weights(
                apply_feedback_to_weights(current_weights, event_topics, "save", direction=-1)
            )
            _safe_bayes_update(db, user.id, event_topics, "save", direction=-1)
            _safe_bandit_update(db, user, event, "save", direction=-1)
            db.commit()
            return {"success": True, "message": "Interaction 'save' removed", "topic_weights": parse_topic_weights(user.topic_weights)}

    db.add(Interaction(user_id=user.id, event_id=event_id, action=action))
    updated_weights = apply_feedback_to_weights(current_weights, event_topics, action)
    user.topic_weights = dump_topic_weights(updated_weights)
    _safe_bayes_update(db, user.id, event_topics, action, direction=1)
    _safe_bandit_update(db, user, event, action, direction=1)
    _safe_memory_extract(db, user, event, action, direction=1)
    db.commit()

    return {"success": True, "message": f"Interaction '{action}' saved", "topic_weights": updated_weights}


def undo_last_interaction(db: Session, telegram_id: int) -> dict:
    """Откатить самое свежее взаимодействие пользователя.

    Под капотом — повторный create_interaction (toggle off): сама ветка
    «existing_same → delete + direction=-1» уже отменяет all-эффекты
    (веса, Bayesian, LinUCB). Поэтому undo сводится к одному вызову.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    last = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.id.desc())
        .first()
    )
    if not last:
        return {"success": False, "message": "Нет действий для отката."}

    action = last.action
    event_id = last.event_id
    # create_interaction сам выполнит toggle off (delete + direction=-1).
    result = create_interaction(db, telegram_id, event_id, action)
    return {
        "success": True,
        "message": f"Откатил последнее: {action} → event {event_id}.",
        "undone": {"action": action, "event_id": event_id},
        "details": result,
    }


def _isolated(db, label: str):
    """SAVEPOINT-обёртка для best-effort side-effects.

    Без неё OperationalError из ненакаченной миграции (или сбой LLM/embedding
    внутри write_memory.flush) переводил Session в aborted-state, и финальный
    db.commit() основной транзакции падал с PendingRollbackError — запись
    Interaction молча терялась, кнопка в боте не перерисовывалась.
    """
    @contextlib.contextmanager
    def _cm():
        sp = db.begin_nested()
        try:
            yield
        except Exception as e:
            logger.warning("%s failed (rolled back savepoint): %s", label, e)
            sp.rollback()
    return _cm()


def _safe_bayes_update(db, user_id: int, event_topics, action: str, direction: int = 1) -> None:
    """Best-effort: не падать на feedback'е, если Bayesian-таблица недоступна."""
    with _isolated(db, "Bayesian update"):
        update_stats_from_feedback(db, user_id, event_topics, action, direction=direction)


def _safe_bandit_update(db, user, event, action: str, direction: int = 1) -> None:
    """Best-effort: обновить LinUCB-параметры по feedback."""
    if not settings.bandit_enabled:
        return
    with _isolated(db, "LinUCB update"):
        from app.recommender.bandit import context_vector, reward_from_action, update_from_feedback
        from app.recommender.hybrid import _parse_event_date, freshness_score
        fresh = freshness_score(_parse_event_date(getattr(event, "date", None)))
        x = context_vector(user, event, fresh)
        reward = reward_from_action(action) * direction
        if reward == 0.0:
            return
        update_from_feedback(db, user.id, x, reward)


def _safe_memory_extract(db, user, event, action: str, direction: int = 1) -> None:
    """Best-effort: long-term memory extract из feedback'а.

    Только для POSITIVE direction — на откат мы ничего не пишем (отдельная
    логика «забыть» не нужна; compaction позже выкинет устаревшее).
    """
    if direction != 1:
        return
    if not getattr(settings, "memory_enabled", True):
        return
    with _isolated(db, "Memory extract"):
        from app.recommender.memory import extract_from_interaction
        extract_from_interaction(db, user, event, action)


_COMPONENT_LABELS_RU = {
    "rule": "совпадение по профилю (темы, формат, город)",
    "cosine": "близость по смыслу описания",
    "bayesian": "история твоих реакций на похожие события",
    "quality": "оценка качества события (от 1 до 10)",
    "hype": "оценка актуальности и интереса (от 1 до 10)",
    "freshness": "свежесть даты — недавние события весят больше",
    "skill_gap": "совпадение с твоими карьерными целями и стеком",
    "bandit": "сигнал «попробуй что-то новое» для разнообразия",
    "gnn": "что выбирают пользователи с похожими интересами",
}


def _build_why_short(breakdown: dict[str, float]) -> str:
    """Короткое объяснение для поп-апа Telegram (≤200 символов)."""
    positive = [(name, val) for name, val in breakdown.items() if val and val > 0.05]
    if not positive:
        return "Подобрано по совпадению темы и формата с твоим профилем."
    positive.sort(key=lambda kv: kv[1], reverse=True)
    short_labels = {
        "rule": "темы", "cosine": "смысл", "bayesian": "история",
        "quality": "качество", "hype": "актуальность", "freshness": "свежесть",
        "skill_gap": "под цели", "bandit": "разнообразие", "gnn": "похожие люди",
    }
    top = positive[:3]
    parts = [f"{short_labels.get(name, name)} +{val:.1f}" for name, val in top]
    return "Главные факторы: " + " · ".join(parts)


def _build_why_full_template(details: dict, event_title: str) -> str:
    """Rule-based развёрнутое объяснение (fallback, без LLM)."""
    lines: list[str] = []
    breakdown = details.get("score_breakdown") or {}
    positive = [(n, v) for n, v in breakdown.items() if v and v > 0.05]
    positive.sort(key=lambda kv: kv[1], reverse=True)

    if positive:
        lines.append("Из чего сложилась рекомендация:")
        for name, val in positive:
            label = _COMPONENT_LABELS_RU.get(name, name)
            lines.append(f"• {label} — вклад {val:.2f}")
        lines.append("")

    if details.get("topic_match"):
        lines.append(f"Совпали темы: {', '.join(details['topic_match'])}.")
    if details.get("format_match"):
        lines.append("Совпал предпочитаемый формат.")
    if details.get("city_match"):
        lines.append("Совпал город.")
    sim = details.get("semantic_similarity")
    if sim is not None:
        lines.append(f"Семантическая близость описания к твоему профилю: {sim:.2f} (от 0 до 1).")
    if details.get("bayesian_posterior") is not None:
        lines.append(
            f"По истории твоих лайков/дизлайков темы события подтверждены с вероятностью "
            f"{details['bayesian_posterior']:.2f}."
        )
    for sig in details.get("history_signals", []):
        lines.append(f"• {sig}")
    if details.get("counterfactual"):
        lines.append("")
        lines.append(details["counterfactual"])

    return "\n".join(lines) if lines else "Подобрано по базовому совпадению профиля."


def _gather_user_evidence(db, user) -> dict:
    """Собрать «улики» о пользователе для конкретного объяснения.

    Возвращает: топ-3 темы профиля, target-роль и целевые скиллы (если есть),
    последние 2 лайкнутых/сохранённых события — чтобы LLM могла привязаться
    к конкретике вроде «как митап X, который ты лайкнул на прошлой неделе».
    """
    out: dict = {
        "top_topics": [], "target_role": None, "target_skills": [],
        "recent_liked_titles": [],
    }
    try:
        weights = parse_topic_weights(user.topic_weights)
        sorted_topics = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        out["top_topics"] = [t for t, _ in sorted_topics[:3]]
    except Exception:
        pass
    try:
        from app.recommender.skill_gap import load_skill_profile
        sp = load_skill_profile(db, user.id)
        if sp:
            out["target_role"] = getattr(sp, "target_role", None)
            target = getattr(sp, "target_skills", None)
            if target:
                out["target_skills"] = target if isinstance(target, list) else []
    except Exception:
        pass
    try:
        recent = (
            db.query(Interaction)
            .filter(Interaction.user_id == user.id, Interaction.action.in_(["like", "save"]))
            .order_by(Interaction.id.desc())
            .limit(2).all()
        )
        if recent:
            ids = [r.event_id for r in recent]
            evs = {e.id: e.title for e in db.query(Event).filter(Event.id.in_(ids)).all()}
            out["recent_liked_titles"] = [evs[i] for i in ids if i in evs]
    except Exception:
        pass
    return out


def _build_why_pair_llm(details: dict, event, user, db) -> tuple[str | None, str | None]:
    """Один LLM-вызов через structured output → (short, full).

    short: 1–2 КОНКРЕТНЫХ предложения для поп-апа (≤180 символов). LLM ОБЯЗАНА
           привязаться к одному конкретному факту: пересекающаяся тема,
           конкретный target_skill, конкретное лайкнутое событие.
    full:  развёрнутый разбор + 1–2 практических совета.

    Числа и метрики НЕ просим у LLM — их добавит rule-based template отдельно.
    Возвращает (None, None) при сбое.
    """
    try:
        from pydantic import BaseModel, Field

        from app.agents.recommendation.llm import llm

        class WhyExplanation(BaseModel):
            short: str = Field(
                ...,
                description="1–2 КОНКРЕТНЫХ предложения, ≤180 символов. "
                "Обязательно сослаться на ОДИН конкретный факт из данных: "
                "название темы, навык, технологию из tech_stack ИЛИ название "
                "лайкнутого события. БЕЗ цифр и БЕЗ слов 'cosine', "
                "'embedding', 'bayesian', 'algorithm'.",
            )
            full: str = Field(
                ...,
                description="3–5 предложений: подробный разбор по нескольким "
                "конкретным фактам, потом 1–2 практических совета (что взять "
                "от события, на каких докладах сосредоточиться). "
                "Без шаблонных фраз.",
            )

        # Достаём конкретику.
        evidence = _gather_user_evidence(db, user)
        common_topics = details.get("topic_match") or []
        recent_titles = evidence.get("recent_liked_titles") or []

        # tech_stack события — конкретные технологии для упоминания
        ev_tech: list[str] = []
        try:
            if event.tech_stack:
                ev_tech = json.loads(event.tech_stack) if isinstance(event.tech_stack, str) else []
        except Exception:
            ev_tech = []

        intersect_skills = []
        target_skills = evidence.get("target_skills") or []
        if target_skills and ev_tech:
            ts_lower = {s.lower() for s in target_skills}
            intersect_skills = [t for t in ev_tech if t.lower() in ts_lower]

        sys_prompt = (
            "Ты — помощник EventMind. Объясняешь, почему пользователю "
            "рекомендовано КОНКРЕТНОЕ событие.\n\n"
            "СТРОГИЕ ПРАВИЛА:\n"
            "1) Опирайся ТОЛЬКО на данные ниже. Не выдумывай спикеров, "
            "программу, формат, дату или содержание докладов.\n"
            "2) ОБЯЗАНО сослаться хотя бы на один КОНКРЕТНЫЙ факт из данных: "
            "конкретная тема пользователя, конкретный target-навык, "
            "конкретная технология из tech_stack события или конкретное "
            "лайкнутое событие.\n"
            "3) ЗАПРЕЩЕНЫ шаблонные фразы: «может быть полезным», «хорошая "
            "возможность», «узнать что-то новое», «расширить кругозор», "
            "«отличное мероприятие», «может быть интересно», «стоит "
            "посетить». Если хочется такое написать — замени на конкретику.\n"
            "4) Если данных мало (новый пользователь без истории) — честно "
            "напиши «у меня пока мало данных о тебе, но темы X и Y из "
            "твоего профиля совпали с этим событием».\n"
            "5) Тон: прямой, дружелюбный, без маркетинга и без воды."
        )

        # Готовим максимально конкретный input
        ev_lines = [
            f"Название: {event.title}",
            f"Формат: {event.format}, город: {event.city}, уровень: {event.level}",
        ]
        if (event.description or "").strip():
            ev_lines.append(f"Описание (фрагмент): {(event.description or '')[:300]}")
        if ev_tech:
            ev_lines.append(f"Технологии в стеке события: {', '.join(ev_tech[:8])}")
        if event.seniority:
            ev_lines.append(f"Целевой опыт аудитории: {event.seniority}")

        prof_lines = [f"Город: {user.city}, предпочитаемый формат: {user.preferred_format}"]
        if evidence["top_topics"]:
            prof_lines.append(f"Топ-3 темы профиля (по весам): {', '.join(evidence['top_topics'])}")
        if evidence["target_role"]:
            prof_lines.append(f"Целевая роль: {evidence['target_role']}")
        if target_skills:
            prof_lines.append(f"Целевые навыки: {', '.join(target_skills[:8])}")
        if recent_titles:
            prof_lines.append(
                "Недавно лайкнул/сохранил: " + " | ".join(f'«{t}»' for t in recent_titles)
            )

        match_lines = []
        if common_topics:
            match_lines.append(f"Пересекающиеся темы: {', '.join(common_topics)}")
        if intersect_skills:
            match_lines.append(
                f"Технологии события, совпавшие с твоими целями: {', '.join(intersect_skills)}"
            )
        if details.get("format_match"):
            match_lines.append("Формат события совпадает с предпочитаемым")
        if details.get("city_match"):
            match_lines.append("Город события совпадает с твоим")
        if details.get("history_signals"):
            match_lines.extend(f"Из истории: {s}" for s in details["history_signals"])
        if not match_lines:
            match_lines.append("Прямых пересечений с явным профилем мало — "
                               "сигнал в основном от семантической близости описания.")

        user_prompt = (
            "СОБЫТИЕ:\n" + "\n".join(ev_lines) + "\n\n"
            "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n" + "\n".join(prof_lines) + "\n\n"
            "ЧТО СОВПАЛО:\n" + "\n".join(match_lines)
        )

        result = llm.with_structured_output(WhyExplanation).invoke(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": user_prompt}]
        )
        if isinstance(result, dict):
            short = (result.get("short") or "").strip()
            full = (result.get("full") or "").strip()
        else:
            short = (getattr(result, "short", "") or "").strip()
            full = (getattr(result, "full", "") or "").strip()
        return (short or None, full or None)
    except Exception as e:
        logger.warning("Why-LLM (structured) failed: %s", e)
        return (None, None)


def get_why_explanation_for_user(db: Session, telegram_id: int, event_id: int) -> dict:
    """Сформировать пару {short, full} для кнопки «Почему?» в боте.

    short → поп-ап (1–2 живых предложения от LLM, при сбое — rule-based).
    full → отдельное сообщение в чате: развёрнутый LLM-разбор + 1–2 совета
           + детальная разбивка по компонентам с числами + counterfactual.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    details = explain_event_detailed(user, event, db=db)
    breakdown = details.get("score_breakdown") or {}

    llm_short, llm_full = _build_why_pair_llm(details, event, user, db)
    template = _build_why_full_template(details, event.title)

    short = llm_short or _build_why_short(breakdown)
    # full = живой LLM-нарратив с советами + сухая разбивка с числами/метриками.
    full = f"{llm_full}\n\n— — —\n\n{template}" if llm_full else template

    return {"short": short, "full": full}


def get_event_interactions_for_user(db: Session, telegram_id: int, event_id: int) -> list[str]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return [
        i.action for i in
        db.query(Interaction).filter(Interaction.user_id == user.id, Interaction.event_id == event_id).all()
    ]


def get_saved_events_for_user(db: Session, telegram_id: int) -> list[dict]:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    saved = db.query(Interaction).filter(Interaction.user_id == user.id, Interaction.action == "save").all()
    if not saved:
        return []

    event_ids = [i.event_id for i in saved]
    events = db.query(Event).filter(Event.id.in_(event_ids)).all()

    return [
        {
            "event_id": e.id,
            "title": e.title,
            "description": e.description,
            "format": e.format,
            "city": e.city,
            "level": e.level,
            "date": e.date,
            "topics": list(_get_event_topic_codes(e)),
            "source_url": e.source_url,
        }
        for e in events
    ]
